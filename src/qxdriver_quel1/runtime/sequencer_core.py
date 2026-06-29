"""Sequencer command classes and execution logic."""

from __future__ import annotations

import logging
from collections.abc import MutableSequence
from typing import Any

import numpy as np
import numpy.typing as npt
from quel_ic_config.quel1_wave_subsystem import CaptureReturnCode

from qxdriver_quel1 import driver as direct
from qxdriver_quel1.classification import ClassificationLineMap
from qxdriver_quel1.driver.capture_result import (
    CaptureResult,
    ClassificationCaptureResult,
    WaveCaptureResult,
)
from qxdriver_quel1.e7awg.compat import (
    CaptureModule,
    CaptureParam,
    DspUnit,
    WaveSequence,
)
from qxdriver_quel1.pulse import (
    CapSampledSequence,
    Capture,
    GenSampledSequence,
    Slot,
    Waveform,
)
from qxdriver_quel1.runtime.box_pool import BoxPool
from qxdriver_quel1.runtime.commands import Command, PortConfigAcquirer, TargetBPC
from qxdriver_quel1.runtime.converter import Converter
from qxdriver_quel1.sysconf import (
    BoxSetting,
    PortSetting,
    Quel1PortType,
    SystemConfigDatabase,
)
from qxdriver_quel1.sysconf.resource_map import ResourceMap

logger = logging.getLogger(__name__)


class Sequencer(Command):
    """Compile sampled sequences into action settings and execute them."""

    def __init__(
        self,
        gen_sampled_sequence: dict[str, GenSampledSequence],
        cap_sampled_sequence: dict[str, CapSampledSequence],
        resource_map: ResourceMap,
        *,
        sysdb: SystemConfigDatabase,
        driver: direct.Quel1System | None = None,
        time_offset: dict[str, int] | None = None,
        time_to_start: dict[str, int] | None = None,
        group_items_by_target: dict[str, dict[int, MutableSequence[Slot]]]
        | None = None,
        interval: float | None = None,
    ):
        if group_items_by_target is None:
            group_items_by_target = {}
        if time_to_start is None:
            time_to_start = {}
        if time_offset is None:
            time_offset = {}
        self.gen_sampled_sequence = gen_sampled_sequence
        self.cap_sampled_sequence = cap_sampled_sequence
        self.group_items_by_terget = group_items_by_target
        self.resource_map = resource_map
        self.syncoffset_by_boxname = time_offset  # taps
        self.timetostart_by_boxname = time_to_start  # sysref
        self.interval = interval
        self.driver = driver

        settings = sysdb.target_settings
        for target_name, gss in gen_sampled_sequence.items():
            if target_name not in settings:
                raise ValueError(f"target({target_name}) is not defined")
            box_names = sysdb.get_boxes_by_target(target_name)
            if not box_names:
                raise ValueError(f"target({target_name}) is not assigned to any box")
            if len(box_names) > 1:
                raise ValueError(f"target({target_name}) is assigned to multiple boxes")
            box_name = next(iter(box_names))
            port_numbers = {
                p
                for p in sysdb.get_port_numbers_by_target(target_name)
                if self.is_output_port(box_name, p)
            }
            if not port_numbers:
                raise ValueError(f"target({target_name}) is not assigned to any port")
            if len(port_numbers) > 1:
                raise ValueError(f"target({target_name}) is assigned to multiple ports")
            port_number = next(iter(port_numbers))
            if not isinstance(port_number, int):
                raise TypeError(
                    f"port_number({port_number}) is not integer, fogi is not supported yet"
                )
            box_skew = sysdb.skew.get(box_name, 0)
            if box_name in sysdb.port_skew:
                port_skew = sysdb.port_skew[box_name].get(port_number, 0)
            else:
                port_skew = 0
            gss.padding += box_skew + port_skew
            logger.debug(
                f"Padding of target({target_name}): box({box_name}), port({port_number}), padding({gss.padding})"
            )

        # {
        #   "box": db._box_settings[box_name],
        #   "port": db._port_settings[port_name],
        #   "channel_number": channel_number,
        #   "target": db._target_settings[target_name],
        # }
        self.sysdb = sysdb
        self._sideload_settings: list[
            direct.AwgSetting | direct.RunitSetting | direct.TriggerSetting
        ] = []

        readout_targets = {
            target
            for target, subseq in group_items_by_target.items()
            for items in subseq.values()
            for item in items
            if isinstance(item, Waveform)
        }
        readout_timings: dict[str, MutableSequence[list[tuple[float, float]]]] = {
            target: [
                [
                    (begin, begin + duration)
                    for item in items
                    if isinstance(item, Waveform)
                    if (begin := item.begin) is not None
                    and (duration := item.duration) is not None
                ]
                for items in group_items_by_target[target].values()
            ]
            for target in readout_targets
        }
        # remove empty items
        readout_timings = {
            target: [item for item in items if item]
            for target, items in readout_timings.items()
        }
        # remove empty subseqs
        readout_timings = {
            target: items for target, items in readout_timings.items() if items
        }
        if readout_timings:
            for target_name, gseq in gen_sampled_sequence.items():
                gseq.readout_timings = readout_timings[target_name]

        readin_targets = {
            target
            for target, subseq in group_items_by_target.items()
            for items in subseq.values()
            for item in items
            if isinstance(item, Capture)
        }
        readin_offsets: dict[str, MutableSequence[list[tuple[float, float]]]] = {
            target: [
                [
                    (begin, begin + duration)
                    for item in items
                    if isinstance(item, Capture)
                    if (begin := item.begin) is not None
                    and (duration := item.duration) is not None
                ]
                for nodeid, items in group_items_by_target[target].items()
            ]
            for target in readin_targets
        }
        # remove empty items
        readin_offsets = {
            target: [item for item in items if item]
            for target, items in readin_offsets.items()
        }
        # remove empty subseqs
        readin_offsets = {
            target: items for target, items in readin_offsets.items() if items
        }
        if readin_offsets:
            for target_name, cseq in cap_sampled_sequence.items():
                cseq.readin_offsets = readin_offsets[target_name]

    def is_output_port(self, box_name: str, port: Quel1PortType) -> bool:
        """Return whether the given port is an output port."""
        if self.driver is None:
            if box_name not in self.sysdb.box_settings:
                raise ValueError(f"box({box_name}) is not defined")
            box = self.sysdb.create_box(box_name, reconnect=True)
            return port in box.get_output_ports()
        else:
            return self.driver.is_output_port(box_name, port)

    def set_measurement_option(
        self,
        repeats: int,
        interval: float,
        integral_mode: str,
        dsp_demodulation: bool = True,
        software_demodulation: bool = False,
        phase_compensation: bool = True,  # TODO not work
        *,
        enable_sum: bool = False,
        enable_classification: bool = False,
        classification_lines: ClassificationLineMap | None = None,
    ) -> None:
        """Set measurement options applied during execution."""
        self.repeats = repeats
        self.interval = interval
        self.integral_mode = integral_mode
        self.dsp_demodulation = dsp_demodulation
        self.software_demodulation = software_demodulation
        self.phase_compensation = phase_compensation
        self.enable_sum = enable_sum
        self.enable_classification = enable_classification
        self.classification_lines = classification_lines

    def generate_cap_resource_map(self, boxpool: BoxPool) -> dict[str, Any]:
        """Build a target-to-capture-resource map."""
        _cap_resource_map: dict[str, MutableSequence[dict[str, Any]]] = {}
        for target_name, ms in self.resource_map.items():
            for m in ms:
                if isinstance(m["box"], BoxSetting):
                    box_name = m["box"].box_name
                else:
                    raise TypeError("box_name is not defined")
                if isinstance(m["port"], PortSetting):
                    port = m["port"].port
                else:
                    raise TypeError("port is not defined")
                if self.driver is None:
                    is_input_port = boxpool.get_port_direction(box_name, port) == "in"
                else:
                    is_input_port = self.driver.is_input_port(box_name, port)
                if is_input_port and target_name in self.cap_sampled_sequence:
                    if target_name in _cap_resource_map:
                        _cap_resource_map[target_name].append(m)
                    else:
                        _cap_resource_map[target_name] = [m]

        return {
            target_name: next(iter(maps))
            for target_name, maps in _cap_resource_map.items()
            if maps
        }

    def calc_first_padding(self) -> int:
        """Calculate first padding required for capture alignment."""
        csseq = self.cap_sampled_sequence
        first_blank = min(
            [seq.prev_blank for sseq in csseq.values() for seq in sseq.sub_sequences]
        )
        return ((first_blank - 1) // 64 + 1) * 64 - first_blank  # Sa

    def generate_e7_settings(
        self,
        boxpool: BoxPool,
    ) -> tuple[
        dict[tuple[str, Quel1PortType, int], CaptureParam],
        dict[tuple[str, Quel1PortType, int], WaveSequence],
        dict[str, Any],
    ]:
        """Generate device-specific capture and generation settings."""
        cap_resource_map = self.generate_cap_resource_map(boxpool)
        _gen_resource_map: dict[str, MutableSequence[dict[str, Any]]] = {}
        for target_name, ms in self.resource_map.items():
            for m in ms:
                if isinstance(m["box"], BoxSetting):
                    box_name = m["box"].box_name
                else:
                    raise TypeError("box_name is not defined")
                if isinstance(m["port"], PortSetting):
                    port = m["port"].port
                else:
                    raise TypeError("port is not defined")
                if self.driver is None:
                    is_output_port = boxpool.get_port_direction(box_name, port) == "out"
                else:
                    is_output_port = self.driver.is_output_port(box_name, port)
                if is_output_port and target_name in self.gen_sampled_sequence:
                    if target_name in _gen_resource_map:
                        _gen_resource_map[target_name].append(m)
                    else:
                        _gen_resource_map[target_name] = [m]
        gen_resource_map: dict[str, Any] = {
            target_name: next(iter(maps))
            for target_name, maps in _gen_resource_map.items()
            if maps
        }

        cap_target_bpc: dict[str, TargetBPC] = {
            target_name: TargetBPC(
                box=boxpool.get_box(m["box"].box_name)[0],
                port=m["port"].port if isinstance(m["port"], PortSetting) else 0,
                channel=m["channel_number"],
                box_name=m["box"].box_name,
            )
            for target_name, m in cap_resource_map.items()
        }
        gen_target_bpc: dict[str, TargetBPC] = {
            target_name: TargetBPC(
                box=boxpool.get_box(m["box"].box_name)[0],
                port=m["port"].port if isinstance(m["port"], PortSetting) else 0,
                channel=m["channel_number"],
                box_name=m["box"].box_name,
            )
            for target_name, m in gen_resource_map.items()
        }
        cap_target_portconf = {
            target_name: PortConfigAcquirer(
                boxpool=boxpool,
                box_name=m["box_name"],
                box=m["box"],
                port=m["port"],
                channel=m["channel"],
                driver=self.driver,
            )
            for target_name, m in cap_target_bpc.items()
        }

        # first_blank = min(
        #     [seq.prev_blank for sseq in csseq.values() for seq in sseq.sub_sequences]
        # )
        # first_padding = ((first_blank - 1) // 64 + 1) * 64 - first_blank  # Sa
        # ref_sequence = next(iter(csseq.values()))
        first_padding = self.calc_first_padding()

        for cseq in self.cap_sampled_sequence.values():
            cseq.padding += first_padding
        for gseq in self.gen_sampled_sequence.values():
            gseq.padding += first_padding

        interval = self.interval if self.interval is not None else 10240
        cap_e7_settings: dict[tuple[str, Quel1PortType, int], CaptureParam] = (
            Converter.convert_to_cap_device_specific_sequence(
                gen_sampled_sequence=self.gen_sampled_sequence,
                cap_sampled_sequence=self.cap_sampled_sequence,
                resource_map=cap_resource_map,
                # target_freq=target_freq,
                port_config=cap_target_portconf,
                repeats=self.repeats,
                interval=interval,
                integral_mode=self.integral_mode,
                dsp_demodulation=self.dsp_demodulation,
                software_demodulation=self.software_demodulation,
                enable_sum=self.enable_sum,
                enable_classification=self.enable_classification,
                classification_lines=self.classification_lines,
            )
        )
        # phase_offset_list_by_target = {
        #     target: [-2 * np.pi * cap_fmod[target] * t for t in reference_time_list]
        #     for target, reference_time_list in reference_time_list_by_target.items()
        # }

        gen_target_portconf = {
            target_name: PortConfigAcquirer(
                boxpool=boxpool,
                box_name=m["box_name"],
                box=m["box"],
                port=m["port"],
                channel=m["channel"],
                driver=self.driver,
            )
            for target_name, m in gen_target_bpc.items()
        }
        gen_e7_settings: dict[tuple[str, Quel1PortType, int], WaveSequence] = (
            Converter.convert_to_gen_device_specific_sequence(
                gen_sampled_sequence=self.gen_sampled_sequence,
                cap_sampled_sequence=self.cap_sampled_sequence,
                resource_map=gen_resource_map,
                port_config=gen_target_portconf,
                repeats=self.repeats,
                interval=interval,
            )
        )
        return cap_e7_settings, gen_e7_settings, cap_resource_map

    def execute(
        self,
        boxpool: BoxPool,
    ) -> tuple[dict[str, CaptureReturnCode], dict[str, list], dict]:
        """Run this sequencer against a runtime box pool."""
        quel1system = (
            self.create_quel1system(boxpool) if self.driver is None else self.driver
        )
        c, g, m = self.generate_e7_settings(boxpool)

        settings: list[
            direct.RunitSetting | direct.AwgSetting | direct.TriggerSetting
        ] = []
        for (name, cport, runit), cprm in c.items():
            settings.append(
                direct.RunitSetting(
                    runit=direct.RunitId(
                        box=name,
                        port=cport,
                        runit=runit,
                    ),
                    cprm=cprm,
                )
            )
        for (name, gport, channel), wseq in g.items():
            settings.append(
                direct.AwgSetting(
                    awg=direct.AwgId(
                        box=name,
                        port=gport,
                        channel=channel,
                    ),
                    wseq=wseq,
                )
            )
        settings += self.select_trigger(quel1system, settings)
        if len(settings) == 0:
            raise ValueError("no settings")

        if self._sideload_settings:
            action = direct.Action.build(
                system=quel1system, settings=self._sideload_settings
            )
        else:
            action = direct.Action.build(system=quel1system, settings=settings)
        status, results = action.action()
        return self.parse_capture_results(status, results, action, m)

    def parse_capture_results(
        self,
        status: dict[tuple[str, Quel1PortType], CaptureReturnCode],
        results: dict[tuple[str, Quel1PortType, int], CaptureResult],
        action: direct.Action,
        crmap: dict[str, Any],
    ) -> tuple[dict[str, CaptureReturnCode], dict[str, list], dict]:
        """Parse raw capture results into target-keyed outputs."""
        bpc2target = {}
        for target, m in crmap.items():
            box, port, channel = m["box"].box_name, m["port"].port, m["channel_number"]
            bpc2target[(box, port, channel)] = target
        data = dict(results)
        cprms = {}
        action_attr = "_action"
        actions_attr = "_actions"
        cprms_attr = "_cprms"
        raw_action = getattr(action, action_attr)
        if isinstance(raw_action, direct.multi.Action):
            for box, act in getattr(raw_action, actions_attr).items():
                for runit_id, cprm in getattr(act, cprms_attr).items():
                    cprms[(box, runit_id.port, runit_id.runit)] = cprm
        elif isinstance(raw_action, tuple):
            box, act = raw_action
            for runit_id, cprm in getattr(act, cprms_attr).items():
                cprms[(box, runit_id.port, runit_id.runit)] = cprm
        rstatus, rresults = {}, {}
        for (box, port, runit), target in bpc2target.items():
            try:
                s, r = self.parse_capture_result(
                    status[(box, port)],
                    data[(box, port, runit)],
                    cprms[(box, port, runit)],
                )
            except KeyError as err:
                raise KeyError(
                    f"capture result not found: {target}:{(box, port, runit)} in {data.keys()}, raw_status:{status}, raw_results:{results}"
                ) from err
            rstatus[target] = s
            rresults[target] = r
        return rstatus, rresults, {}

    def parse_capture_result(
        self,
        status: CaptureReturnCode,
        data: CaptureResult,
        cprm: CaptureParam,
    ) -> tuple[
        CaptureReturnCode,
        list[npt.NDArray[np.complex64] | npt.NDArray[np.uint8]],
    ]:
        # num_expected_words = cprm.calc_capture_samples()
        """Parse one capture payload according to capture parameters."""
        if isinstance(data, ClassificationCaptureResult):
            return status, [np.asarray(section).reshape(-1) for section in data.labels]

        if not isinstance(data, WaveCaptureResult):
            raise TypeError(f"unsupported capture result: {data!r}")

        data_array = np.asarray(data.sections[0])
        if DspUnit.INTEGRATION in cprm.dsp_units_enabled:
            data_array = data_array.reshape(1, -1)
        else:
            data_array = data_array.reshape(cprm.num_integ_sections, -1)
        if DspUnit.SUM in cprm.dsp_units_enabled:
            width = len(cprm.sum_section_list)
            result = np.hsplit(data_array, width)
        else:
            b = DspUnit.DECIMATION not in cprm.dsp_units_enabled
            ssl = cprm.sum_section_list
            ws = [w if b else int(w // 4) for w, _ in ssl[:-1]]
            word = cprm.NUM_SAMPLES_IN_ADC_WORD
            width = np.cumsum(np.array(ws))
            result = np.hsplit(data_array, width * word)
        return status, result

    def create_quel1system(self, boxpool: BoxPool) -> direct.Quel1System:
        """Create a `Quel1System` from current box-pool resources."""
        if boxpool.clock_master is None:
            raise ValueError("clock master is not set")
        quel1system = direct.Quel1System.create(
            clockmaster=boxpool.clock_master,
            boxes=[
                direct.NamedBox(name, box) for name, (box, _) in boxpool.boxes.items()
            ],
        )
        quel1system.trigger = self.sysdb.trigger
        for box_name, timing_shift in self.sysdb.timing_shift.items():
            quel1system.timing_shift[box_name] = timing_shift
        quel1system.displacement = self.sysdb.time_to_start
        return quel1system

    def convert(
        self,
        cap_e7_settings: dict[tuple[str, int, int], CaptureParam],
        gen_e7_settings: dict[tuple[str, int, int], WaveSequence],
    ) -> list[direct.AwgSetting | direct.RunitSetting | direct.TriggerSetting]:
        """Convert e7 settings into direct-driver setting objects."""
        settings: list[
            direct.AwgSetting | direct.RunitSetting | direct.TriggerSetting
        ] = []
        for (box_name, port, runit), e7 in cap_e7_settings.items():
            settings.append(
                direct.RunitSetting(
                    runit=direct.RunitId(box=box_name, port=port, runit=runit),
                    cprm=e7,
                )
            )
        for (box_name, port, channel), e7 in gen_e7_settings.items():
            settings.append(
                direct.AwgSetting(
                    awg=direct.AwgId(box=box_name, port=port, channel=channel),
                    wseq=e7,
                )
            )
        return settings

    @staticmethod
    def is_empty_trigger(
        settings: list[direct.AwgSetting | direct.RunitSetting | direct.TriggerSetting],
    ) -> bool:
        """Return whether trigger settings are absent."""
        return all(not isinstance(s, direct.TriggerSetting) for s in settings)

    def select_trigger(
        self,
        quel1system: direct.Quel1System,
        settings: list[direct.AwgSetting | direct.RunitSetting | direct.TriggerSetting],
    ) -> list[direct.TriggerSetting]:
        """Select trigger settings from AWG and capture assignments."""
        if not self.is_empty_trigger(settings):
            raise ValueError("trigger is already set")

        result: list[direct.TriggerSetting] = []
        caps: list[tuple[int, direct.RunitId]] = []
        gens: list[tuple[int, direct.AwgId]] = []
        decode_port_name = "_decode_port"
        convert_any_port_name = "_convert_any_port"
        for setting in settings:
            if isinstance(setting, direct.RunitSetting):
                box = quel1system.box[setting.runit.box]
                decode_port = getattr(box, decode_port_name)
                convert_any_port = getattr(box, convert_any_port_name)
                port, _ = decode_port(setting.runit.port)
                group, _ = convert_any_port(port)
                # capmod = box.rmap.get_capture_module_of_rline(group, rline)
                caps.append((group, setting.runit))
            elif isinstance(setting, direct.AwgSetting):
                box = quel1system.box[setting.awg.box]
                decode_port = getattr(box, decode_port_name)
                convert_any_port = getattr(box, convert_any_port_name)
                port, _ = decode_port(setting.awg.port)
                group, _ = convert_any_port(port)
                gens.append((group, setting.awg))
        defined_awgs = [s.awg for s in settings if isinstance(s, direct.AwgSetting)]
        for _runit_group, runit_id in caps:
            if (runit_id.box, runit_id.port) in quel1system.trigger:
                trig_name, trig_nport, trig_nchannel = quel1system.trigger[
                    (runit_id.box, runit_id.port)
                ]
                awg = direct.AwgId(
                    box=trig_name, port=trig_nport, channel=trig_nchannel
                )
                if runit_id.box != trig_name:
                    raise ValueError(
                        f"invalid trigger {runit_id.box, runit_id.port} for {trig_name, trig_nport, trig_nchannel}"
                    )
                if awg not in defined_awgs:
                    raise ValueError(
                        f"trigger {trig_name, trig_nport, trig_nchannel} not found in settings"
                    )
                result.append(
                    direct.TriggerSetting(
                        triggerd_port=runit_id.port,
                        trigger_awg=awg,
                    )
                )
        if all([bool(caps), not bool(gens)]) or all([not bool(caps), bool(gens)]):
            return result
        pre_defined_triggers = {(s.trigger_awg.box, s.triggerd_port) for s in result}
        for runit_group, runit_id in caps:
            if (runit_id.box, runit_id.port) in pre_defined_triggers:
                continue
            for awg_group, awg_id in gens:
                if runit_id.box == awg_id.box and runit_group == awg_group:
                    result.append(
                        direct.TriggerSetting(
                            triggerd_port=runit_id.port,
                            trigger_awg=awg_id,
                        )
                    )
                    break
            for _awg_group, awg_id in gens:
                if runit_id.box == awg_id.box:
                    result.append(
                        direct.TriggerSetting(
                            triggerd_port=runit_id.port,
                            trigger_awg=awg_id,
                        )
                    )
                    break
            else:
                raise ValueError("invalid trigger")
        return result

    @classmethod
    def convert_key_from_bmu_to_target(
        cls,
        bmc_target: dict[tuple[str | None, CaptureModule, int | None], str],
        status: dict[tuple[str, CaptureModule], CaptureReturnCode],
        iqs: dict[tuple[str, CaptureModule], dict[int, list]],
    ) -> tuple[dict[str, CaptureReturnCode], dict[str, list]]:
        """Convert BMU-keyed capture outputs into target-keyed outputs."""
        _iqs = {
            bmc_target[(box_name, capm, capu)]: __iqs
            for (box_name, capm), _ in iqs.items()
            for capu, __iqs in _.items()
        }
        _status = {
            bmc_target[(box_name, capm, capu)]: status[(box_name, capm)]
            for (box_name, capm), _ in iqs.items()
            for capu in _
        }

        # sort keys of iqs by target name
        sorted_iqs = {key: _iqs[key] for key in sorted(_iqs)}

        return _status, sorted_iqs
