"""Core calibration orchestration APIs and execution utilities."""

from __future__ import annotations

import functools
import json
import logging
import math
import operator
import os
import warnings
from collections import Counter
from collections.abc import Iterable, MutableMapping, MutableSequence
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Final,
    TypedDict,
)

import numpy as np
import numpy.typing as npt
from quel_ic_config import (
    QUEL1_BOXTYPE_ALIAS,
    Quel1Box,
    Quel1BoxType,
    Quel1ConfigOption,
)
from quel_ic_config.quel1_wave_subsystem import CaptureReturnCode
from typing_extensions import deprecated

from . import __version__, neopulse
from .clockmaster_compat import QuBEMasterClient, SequencerClient
from .e7compat import CaptureModule, CaptureParam, DspUnit, WaveSequence
from .e7utils import (
    CaptureParamTools,
    WaveSequenceTools,
    _convert_gen_sampled_sequence_to_blanks_and_waves_chain,
)
from .instrument.quel.quel1 import driver as direct
from .neopulse import (
    CapSampledSequence,
    Capture,
    GenSampledSequence,
    GenSampledSubSequence,
    Slot,
    Waveform,
)
from .resource_map import ResourceMap, create_target_resource_map
from .runtime.box_pool import BoxPool
from .runtime.executor import Executor
from .sysconfdb import BoxSetting, PortSetting, Quel1PortType, SystemConfigDatabase

logger = logging.getLogger(__name__)

Quel1BoxWithRawWss = Quel1Box


class Direction(Enum):
    """Define signal direction relative to logical targets."""

    FROM_TARGET = "from_target"
    TO_TARGET = "to_target"


class Sideband(Enum):
    """Define sideband labels used by mixer configuration."""

    UpperSideBand = "U"
    LowerSideBand = "L"


DEFAULT_SIDEBAND = "U"


class QubeCalib:
    """Orchestrate configuration management and sequence execution."""

    def __init__(
        self,
        path_to_database_file: str | os.PathLike | None = None,
    ) -> None:
        self._system_config_database: Final[SystemConfigDatabase] = (
            SystemConfigDatabase()
        )
        self._executor: Final[Executor] = Executor(self._system_config_database)
        self._box_configs: dict[str, dict[str, Any]] = {}

        if path_to_database_file is not None:
            self.system_config_database.load(path_to_database_file)

    @classmethod
    def from_yaml(
        cls,
        *,
        box_yaml: str = "",
        skew_yaml: str = "",
        clockmaster_ip: str = "",
    ) -> QubeCalib:
        """Build an instance from YAML-based system definitions."""
        self = cls()
        if box_yaml != "":
            self.sysdb.load_box_yaml(box_yaml)
        if skew_yaml != "":
            self.sysdb.load_skew_yaml(skew_yaml)
        if clockmaster_ip != "":
            self.sysdb.define_clockmaster(clockmaster_ip, reset=False)
        return self

    def new_session(self) -> Executor:
        """Create a new session."""
        return Executor(self.system_config_database.copy())

    @property
    def version(self) -> str:
        """Return version."""
        return __version__

    @property
    def system_config_database(self) -> SystemConfigDatabase:
        """Return system config database."""
        return self._system_config_database

    @property
    def sysdb(self) -> SystemConfigDatabase:
        """Return sysdb."""
        return self._system_config_database

    @property
    def executor(self) -> Executor:
        """Return the underlying command executor."""
        return self._executor

    @property
    def Quel1BoxType(self) -> type[Quel1BoxType]:
        """Return Quel1BoxType."""
        return Quel1BoxType

    @deprecated("use sysdb.create_quel1system() instead")
    def create_quel1system(self, box_names: list[str]) -> direct.Quel1System:
        """Create a `Quel1System` from configured box names."""
        return self.sysdb.create_quel1system(*box_names)

    @deprecated("use sysdb.create_quel1system() instead")
    def quel1_create_quel1system(self, *box_names: str) -> direct.Quel1System:
        """Create a `Quel1System` through the direct compatibility path."""
        clockmaster_setting = self.sysdb.clockmaster_setting
        if clockmaster_setting is None:
            raise ValueError("clock master is not found")
        system = direct.Quel1System.create(
            clockmaster=QuBEMasterClient(str(clockmaster_setting.ipaddr)),
            boxes=[self.sysdb.create_named_box(b) for b in box_names],
        )
        return system

    def execute(self) -> tuple:
        """Run queued commands."""
        return self._executor.execute()

    def step_execute(
        self,
        repeats: int = 1,
        interval: float = 10240,
        integral_mode: str = "integral",  # "single"
        dsp_demodulation: bool = True,
        software_demodulation: bool = False,
    ) -> Executor:
        """Prepare runtime state and return an execution iterator."""
        return self._executor.step_execute(
            repeats=repeats,
            interval=interval,
            integral_mode=integral_mode,
            dsp_demodulation=dsp_demodulation,
            software_demodulation=software_demodulation,
        )

    def show_log(
        self,
        name: str = "qubecalib",
        *,
        level: int = logging.DEBUG,
        handler: logging.Handler | None = None,
        formatter: logging.Formatter | None = None,
    ) -> logging.Logger:
        """Configure and return a logger for calibration operations."""
        if handler is None:
            handler = logging.StreamHandler()
        if formatter is None:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        handler.setFormatter(formatter)
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(level)
        return logger

    def modify_target_frequency(self, target_name: str, frequency: float) -> None:
        """Update the configured frequency for a target."""
        self.system_config_database.set_target_frequency(
            target_name=target_name,
            frequency=frequency,
        )

    def add_rfswitch(self, box_name: str, port: int, rfswitch: str) -> None:
        """(block / pass), (loop / open)."""
        self._executor.add_command(RfSwitch(box_name, port, rfswitch))

    def add_sequence(
        self,
        sequence: neopulse.Sequence,
        *,
        driver: direct.Quel1System | None = None,
        interval: float | None = None,
        time_offset: dict[str, int] | None = None,  # {box_name: time_offset}
        time_to_start: dict[str, int] | None = None,  # {box_name: time_to_start}
    ) -> None:
        """Convert and queue a sequence for execution."""
        if time_to_start is None:
            time_to_start = {}
        if time_offset is None:
            time_offset = {}
        gen_sampled_sequence, cap_sampled_sequence = (
            sequence.convert_to_sampled_sequence()
        )

        items_by_target = sequence.get_group_items_by_target()

        targets = set(list(gen_sampled_sequence) + list(cap_sampled_sequence))
        resource_map = self._create_target_resource_map(targets)

        self._executor.add_command(
            Sequencer(
                gen_sampled_sequence=gen_sampled_sequence,
                cap_sampled_sequence=cap_sampled_sequence,
                resource_map=resource_map,
                group_items_by_target=items_by_target,
                time_offset=time_offset,
                time_to_start=time_to_start,
                interval=interval,
                sysdb=self.system_config_database,
                driver=driver,
            )
        )

    def define_target(
        self,
        target_name: str,
        channel_name: str,
        target_frequency: float | None = None,
    ) -> None:
        """Define a target mapping and optional frequency."""
        db = self.system_config_database
        db.assign_target_to_channel(target=target_name, channel=channel_name)
        if target_frequency is None and target_name not in db.target_settings:
            raise ValueError(f"frequency of target({target_name}) is not defined")
        if target_frequency is not None:
            db.set_target_frequency(target_name=target_name, frequency=target_frequency)

    def define_clockmaster(
        self,
        ipaddr: str,
        reset: bool,
    ) -> None:
        """Define the clock master endpoint in the system database."""
        return self.system_config_database.define_clockmaster(
            ipaddr,
            reset,
        )

    def define_box(
        self,
        box_name: str,
        ipaddr_wss: str,
        boxtype: str,
        ipaddr_sss: str | None = None,
        ipaddr_css: str | None = None,
        config_root: str | None = None,
        config_options: MutableSequence[Quel1ConfigOption] | None = None,
    ) -> dict[str, Any]:
        """Register one box definition in the system database."""
        if config_options is None:
            config_options = []
        return self.system_config_database.define_box(
            box_name=box_name,
            ipaddr_wss=ipaddr_wss,
            boxtype=boxtype,
            config_options=config_options,
            ipaddr_sss=ipaddr_sss,
            ipaddr_css=ipaddr_css,
            # config_root=config_root,
        )

    def define_channel(
        self,
        channel_name: str,
        port_name: str,
        channel_number: int,
        ndelay_or_nwait: int = 0,
    ) -> None:
        """Bind a logical channel to a physical port channel."""
        self.system_config_database.define_channel(
            channel_name=channel_name,
            port_name=port_name,
            channel_number=channel_number,
            ndelay_or_nwait=ndelay_or_nwait,
        )

    def define_port(
        self,
        port_name: str,
        box_name: str,
        port_number: int,
        lo_freq: float | None = None,
        cnco_freq: float | None = None,
        sideband: str = DEFAULT_SIDEBAND,
        vatt: int = 0x800,
        fnco_freq: tuple[float]
        | tuple[float, float]
        | tuple[float, float, float]
        | None = None,
    ) -> None:
        """Register one logical port mapping."""
        self.system_config_database.define_port(
            port_name=port_name,
            box_name=box_name,
            port_number=port_number,
            lo_freq=lo_freq,
            cnco_freq=cnco_freq,
            sideband=sideband,
            vatt=vatt,
            fnco_freq=fnco_freq,
        )

    def _create_target_resource_map(
        self,
        target_names: Iterable[str],
    ) -> ResourceMap:
        return create_target_resource_map(
            sysdb=self.system_config_database,
            target_names=target_names,
        )

    def get_target_info(self, target_name: str) -> dict:
        """Return metadata for a target."""
        return {
            "box_name": self.system_config_database.get_boxes_by_target(
                target_name=target_name
            ),
            "port": self.system_config_database.get_ports_by_target(
                target_name=target_name
            ),
            "channel": self.system_config_database.get_channel_numbers_by_target(
                target_name=target_name
            ),
            "target_frequency": self.system_config_database.target_settings[
                target_name
            ]["frequency"],
        }

    def get_box_names_by_targets(self, *target_names: str) -> set[str]:
        """Return unique box names that own the given targets."""
        return set(
            functools.reduce(
                operator.iadd,
                [
                    list(self.get_target_info(target_name)["box_name"])
                    for target_name in target_names
                ],
                [],
            )
        )

    def get_box_name_by_alias(self, alias: str) -> str:
        """Resolve a configured box alias."""
        return self.system_config_database.box_aliases[alias]

    def create_box(
        self,
        box_name: str,
        reconnect: bool = True,
    ) -> Quel1BoxWithRawWss:
        """Create and optionally reconnect a box by name."""
        return self.system_config_database.create_box(
            box_name=box_name,
            reconnect=reconnect,
        )

    @deprecated("use sysdb.create_named_box() instead")
    def create_named_box(
        self, box_name: str, *, reconnect: bool = True
    ) -> direct.NamedBox:
        """Create a named-box wrapper for direct driver operations."""
        return direct.NamedBox(
            name=box_name,
            box=self.create_box(
                box_name,
                reconnect=reconnect,
            ),
        )

    def read_clock(self, *box_names: str) -> MutableSequence[tuple[bool, int, int]]:
        """Read clocks from the specified boxes."""
        return [
            SequencerClient(
                target_ipaddr=str(
                    self.system_config_database.box_settings[_].ipaddr_sss
                ),
                box=self.system_config_database.create_box(_, reconnect=False),
            ).read_clock()
            for _ in box_names
        ]

    def resync(
        self, *box_names: str
    ) -> list[tuple[bool, int] | MutableSequence[tuple[bool, int, int]]]:
        """Issue a clock resynchronization and return measured clocks."""
        db = self.system_config_database
        clockmaster_setting = db.clockmaster_setting
        if clockmaster_setting is None:
            raise ValueError("clock master is not found")
        master = QuBEMasterClient(master_ipaddr=str(clockmaster_setting.ipaddr))
        master.kick_clock_synch([str(db.box_settings[_].ipaddr_sss) for _ in box_names])
        return [self.read_clock(_) for _ in box_names] + [master.read_clock()]

    def show_available_boxtype(self) -> MutableSequence[str]:
        """Return available QuEL-1 box-type aliases."""
        return list(QUEL1_BOXTYPE_ALIAS)

    @classmethod
    def quantize_sequence_duration(
        cls,
        sequence_duration: float,
        constrain: float = 10_240,
    ) -> float:
        """Quantize a sequence duration to a hardware-friendly grid."""
        return sequence_duration // constrain * constrain

    def get_all_box_configs(self) -> dict[str, dict[str, Any]]:
        """Return `dump_box()` payloads for all configured boxes."""
        return {
            box_name: self.system_config_database.create_box(box_name).dump_box()
            for box_name in self.system_config_database.box_settings
        }

    def store_all_box_configs(self, path_to_config_file: str | os.PathLike) -> None:
        """Persist current box configurations to a JSON file."""
        with open(Path(os.getcwd()) / Path(path_to_config_file), "w") as fp:
            json.dump(
                self.get_all_box_configs(),
                fp,
                indent=4,
            )

    def load_all_box_configs(self, path_to_config_file: str | os.PathLike) -> None:
        """Load cached box configurations from a JSON file."""
        with open(Path(os.getcwd()) / Path(path_to_config_file)) as fp:
            configs = json.load(fp)
        for _ in configs.values():
            ports: dict[int | tuple[int, int], dict[str, Any]] = {
                int(k): v for k, v in _["ports"].items()
            }
            _["ports"] = ports
            for port_config in ports.values():
                if "channels" in port_config:
                    port_config["channels"] = {
                        int(k): v for k, v in port_config["channels"].items()
                    }
                if "runits" in port_config:
                    port_config["runits"] = {
                        int(k): v for k, v in port_config["runits"].items()
                    }
        self._box_configs = configs

    def apply_all_box_configs(self) -> None:
        """Apply all cached box configurations."""
        for box_name in self._box_configs:
            self._apply_box_config(box_name)

    def _apply_box_config(self, box_name: str) -> None:
        box = self.create_box(box_name)
        box.config_box(self._box_configs[box_name]["ports"])

    def apply_box_config(self, *target_names: str) -> set[str]:
        """Apply cached configurations to boxes that own given targets."""
        box_names = self.get_box_names_by_targets(*target_names)
        for box_name in box_names:
            self._apply_box_config(box_name)
        return box_names

    def clear_command_queue(self) -> None:
        """Clear the executor command queue."""
        self._executor.clear_command_queue()

    def show_command_queue(self) -> MutableSequence:
        """Return the current executor command queue."""
        return self._executor.command_queue

    def create_boxpool(self, *box_names: str) -> BoxPool:
        """Create and initialize a runtime box pool."""
        boxpool = BoxPool()
        clockmaster_setting = self.system_config_database.clockmaster_setting
        if clockmaster_setting is not None:
            boxpool.create_clock_master(
                ipaddr=str(clockmaster_setting.ipaddr),
            )
        for box_name in box_names:
            if box_name not in self.system_config_database.box_settings:
                raise ValueError(f"box({box_name}) is not defined")
            setting = self.system_config_database.box_settings[box_name]
            box = boxpool.create(
                box_name,
                ipaddr_wss=str(setting.ipaddr_wss),
                ipaddr_sss=str(setting.ipaddr_sss),
                ipaddr_css=str(setting.ipaddr_css),
                boxtype=setting.boxtype,
                # config_root=Path(setting.config_root)
                # if setting.config_root is not None
                # else None,
                # config_options=setting.config_options,
            )
            box.reconnect()
        return boxpool


class Converter:
    """Convert sampled sequences into hardware-specific settings."""

    @classmethod
    def convert_to_device_specific_sequence(
        cls,
        gen_sampled_sequence: dict[str, GenSampledSequence],
        cap_sampled_sequence: dict[str, CapSampledSequence],
        resource_map: dict[
            str, dict[str, BoxSetting | PortSetting | int | dict[str, float]]
        ],
        port_config: dict[str, PortConfigAcquirer],
        repeats: int,
        interval: float,
        integral_mode: str,
        dsp_demodulation: bool,
        software_demodulation: bool,
        enable_sum: bool,
        enable_classification: bool = False,
        line_param0: tuple[float, float, float] = (1, 0, 0),
        line_param1: tuple[float, float, float] = (0, 1, 0),
    ) -> dict[tuple[str, Quel1PortType, int], WaveSequence | CaptureParam]:
        """Convert sampled sequences into capture/generation settings."""
        capseq = cls.convert_to_cap_device_specific_sequence(
            gen_sampled_sequence=gen_sampled_sequence,
            cap_sampled_sequence=cap_sampled_sequence,
            resource_map={
                target_name: _
                for target_name, _ in resource_map.items()
                if target_name in cap_sampled_sequence
            },
            port_config={
                target_name: _
                for target_name, _ in port_config.items()
                if target_name in cap_sampled_sequence
            },
            repeats=repeats,
            interval=interval,
            integral_mode=integral_mode,
            dsp_demodulation=dsp_demodulation,
            software_demodulation=software_demodulation,
            enable_sum=enable_sum,
            enable_classification=enable_classification,
            line_param0=line_param0,
            line_param1=line_param1,
        )
        genseq = cls.convert_to_gen_device_specific_sequence(
            gen_sampled_sequence=gen_sampled_sequence,
            cap_sampled_sequence=cap_sampled_sequence,
            resource_map={
                target_name: _
                for target_name, _ in resource_map.items()
                if target_name in gen_sampled_sequence
            },
            port_config={
                target_name: _
                for target_name, _ in port_config.items()
                if target_name in gen_sampled_sequence
            },
            repeats=repeats,
            interval=interval,
        )
        return genseq | capseq

    @classmethod
    def convert_to_cap_device_specific_sequence(
        cls,
        gen_sampled_sequence: dict[str, GenSampledSequence],
        cap_sampled_sequence: dict[str, CapSampledSequence],
        resource_map: dict[
            str, dict[str, BoxSetting | PortSetting | int | dict[str, float]]
        ],
        port_config: dict[str, PortConfigAcquirer],
        repeats: int,
        interval: float,
        integral_mode: str,
        dsp_demodulation: bool,
        software_demodulation: bool,
        enable_sum: bool,
        enable_classification: bool = False,
        line_param0: tuple[float, float, float] = (1, 0, 0),
        line_param1: tuple[float, float, float] = (0, 1, 0),
    ) -> dict[tuple[str, Quel1PortType, int], CaptureParam]:
        """Build capture settings from sampled sequences."""
        ndelay_or_nwait_by_target = {
            target_name: rmap["port"].ndelay_or_nwait[rmap["channel_number"]]
            if rmap["port"].ndelay_or_nwait is not None
            else 0
            for target_name, rmap in resource_map.items()
            if isinstance(rmap["port"], PortSetting)
            and isinstance(rmap["channel_number"], int)
        }
        targets_freqs: MutableMapping[str, float] = {
            target_name: cls.calc_modulation_frequency(
                f_target=rmap["target"]["frequency"],
                port_config=port_config[target_name],
            )
            for target_name, rmap in resource_map.items()
            if isinstance(rmap["target"], dict)
        }
        for target_name, freq in targets_freqs.items():
            cap_sampled_sequence[target_name].modulation_frequency = freq
        targets_ids = {
            target_name: (
                rmap["box"].box_name,
                rmap["port"].port,
                rmap["channel_number"],
            )
            for target_name, rmap in resource_map.items()
            if isinstance(rmap["box"], BoxSetting)
            and isinstance(rmap["port"], PortSetting)
            and isinstance(rmap["channel_number"], int)
        }
        ids_targets = {id: target_name for target_name, id in targets_ids.items()}
        if len(targets_ids) != len(ids_targets):
            raise ValueError("multiple targets are assigned.")

        if not all(
            _ == 1
            for _ in Counter([targets_ids[_] for _ in cap_sampled_sequence]).values()
        ):
            raise ValueError(
                "multiple access for single runit will be supported, not now"
            )
        sseqs = list(cap_sampled_sequence.values())
        # fps = [padding] + len(sseqs[1:]) * [0]
        # lbs = len(sseqs[:-1]) * [0] + [padding]
        ids_e7 = {
            targets_ids[sseq.target_name]: CaptureParamTools.create(
                sequence=sseq,
                capture_delay_words=ndelay_or_nwait_by_target[sseq.target_name] * 16,
                repeats=repeats,
                interval_samples=int(interval / sseq.sampling_period),  # samples
            )
            for sseq in sseqs
        }
        if integral_mode == "integral":
            ids_e7 = {
                id: CaptureParamTools.enable_integration(capprm=e7)
                for id, e7 in ids_e7.items()
            }
        if dsp_demodulation:
            ids_e7 = {
                id: CaptureParamTools.enable_demodulation(
                    capprm=e7,
                    f_GHz=targets_freqs[ids_targets[id]],
                )
                for id, e7 in ids_e7.items()
            }
        if enable_sum:
            ids_e7 = {
                id: CaptureParamTools.enable_sum(capprm=e7) for id, e7 in ids_e7.items()
            }
        if enable_classification:
            ids_e7 = {
                id: CaptureParamTools.enable_classification(
                    capprm=e7, line_param0=line_param0, line_param1=line_param1
                )
                for id, e7 in ids_e7.items()
            }
        return ids_e7

    @classmethod
    def convert_to_gen_device_specific_sequence(
        cls,
        gen_sampled_sequence: dict[str, GenSampledSequence],
        cap_sampled_sequence: dict[str, CapSampledSequence],
        resource_map: dict[
            str, dict[str, BoxSetting | PortSetting | int | dict[str, float]]
        ],
        port_config: dict[str, PortConfigAcquirer],
        repeats: int,
        interval: float,
    ) -> dict[tuple[str, Quel1PortType, int], WaveSequence]:
        # for target_name, gss in gen_sampled_sequence.items():
        #     print(target_name, gss.padding, end=" ")
        #     # for sub in gss.sub_sequences:
        #     #     print(sub.padding, end=" ")
        # print()
        """Build generation settings from sampled sequences."""
        SAMPLING_PERIOD = 2

        targets_freqs: MutableMapping[str, float] = {}
        targets_ids: MutableMapping[str, tuple[str, Quel1PortType, int]] = {}
        for target_name, rmap in resource_map.items():
            rmap_target = rmap["target"]
            if not isinstance(rmap_target, dict):
                raise TypeError("target is not defined")
            targets_freqs[target_name] = cls.calc_modulation_frequency(
                f_target=rmap_target["frequency"],
                port_config=port_config[target_name],
            )

            # targets_freqs = {
            #     target_name: cls.calc_modulation_frequency(
            #         f_target=rmap["target"]["frequency"],
            #         port_config=port_config[target_name],
            #     )
            #     for target_name, rmap in resource_map.items()
            # }

            rmap_box = rmap["box"]
            if not isinstance(rmap_box, BoxSetting):
                raise TypeError("box is not defined")
            rmap_port = rmap["port"]
            if not isinstance(rmap_port, PortSetting):
                raise TypeError("port is not defined")
            rmap_channel_number = rmap["channel_number"]
            if not isinstance(rmap_channel_number, int):
                raise TypeError("channel_number is not defined")
            targets_ids[target_name] = (
                rmap_box.box_name,
                rmap_port.port,
                rmap_channel_number,
            )

        for target_name, freq in targets_freqs.items():
            gen_sampled_sequence[target_name].modulation_frequency = freq
        for target, seq in gen_sampled_sequence.items():
            if target not in cap_sampled_sequence:
                continue
            modulation_angular_frequency = 2 * np.pi * targets_freqs[target]
            timing_list = seq.readout_timings
            offset_list = cap_sampled_sequence[target].readin_offsets
            if timing_list is None and offset_list is None:
                continue
            if timing_list is None:
                raise ValueError("readout_timings is not defined")
            if offset_list is None:
                raise ValueError("readin_offsets is not defined")
            for subseq, timings, offsets in zip(
                seq.sub_sequences, timing_list, offset_list, strict=False
            ):
                wave = subseq.real + 1j * subseq.imag
                for (begin, end), (offsetb, _) in zip(timings, offsets, strict=False):
                    offset_phase = modulation_angular_frequency * offsetb
                    b = math.floor(begin / SAMPLING_PERIOD)
                    e = math.floor(end / SAMPLING_PERIOD)
                    wave[b:e] = wave[b:e] * np.exp(-1j * offset_phase)
                subseq.real = np.real(wave)
                subseq.imag = np.imag(wave)

        ndelay_or_nwait_by_id = {
            id: next(
                iter(
                    {
                        rmap["port"].ndelay_or_nwait[rmap["channel_number"]]
                        for rmap in resource_map.values()
                        if isinstance(rmap["box"], BoxSetting)
                        and isinstance(rmap["port"], PortSetting)
                        and isinstance(rmap["channel_number"], int)
                        if rmap["box"].box_name == id[0]
                        and rmap["port"].port == id[1]
                        and rmap["channel_number"] == id[2]
                    }
                )
            )
            for id in targets_ids.values()
        }
        ids_sampled_sequences: dict[
            tuple[str, Quel1PortType, int], dict[str, GenSampledSequence]
        ] = {}
        for target, box_port_channel in targets_ids.items():
            if target in gen_sampled_sequence:
                if box_port_channel not in ids_sampled_sequences:
                    ids_sampled_sequences[box_port_channel] = {}
                ids_sampled_sequences[box_port_channel][target] = gen_sampled_sequence[
                    target
                ]
        # ids_sampled_sequences = {
        #     id: {
        #         _: sampled_sequence[_]
        #         for _, _id in targets_ids.items()
        #         if _id == id and _ in sampled_sequence
        #     }
        #     for id in targets_ids.values()
        # }
        ids_modfreqs = {
            id: {_: targets_freqs[_] for _, _id in targets_ids.items() if _id == id}
            for id in targets_ids.values()
        }
        for seq in gen_sampled_sequence.values():
            padding = seq.padding
            subseq = seq.sub_sequences[0]
            subseq.real = np.concatenate([np.zeros(padding), subseq.real])
            subseq.imag = np.concatenate([np.zeros(padding), subseq.imag])
        ids_muxed_sequences = {
            id: cls.multiplex(
                sequences=ids_sampled_sequences[id],
                modfreqs=ids_modfreqs[id],
            )
            for id in ids_sampled_sequences
        }
        return {
            id: WaveSequenceTools.create(
                sequence=ids_muxed_sequences[id],
                # wait_words=wait_words,
                wait_words=ndelay_or_nwait_by_id[id],
                repeats=repeats,
                interval_samples=int(
                    interval / ids_muxed_sequences[id].sampling_period
                ),
            )
            for id in ids_sampled_sequences
        }

    @classmethod
    def calc_modulation_frequency_for_direct_conversion_transceiver(
        cls,
        f_target: float,
        port_config: PortConfigAcquirer,
    ) -> float:
        """Calculate modulation frequency for direct-conversion transceivers."""
        f_cnco = port_config.cnco_freq * 1e-9  # Hz -> GHz
        f_fnco = port_config.fnco_freq * 1e-9  # Hz -> GHz
        f_diff = f_target - (f_cnco + f_fnco)
        if abs(f_diff) > 0.5:
            p = port_config
            warnings.warn(
                f"Modulation frequency abs({f_diff}) of {p.box_name}:{p.port}:{p.channel} is too high. f_target={f_target} GHz, f_cnco={f_cnco} GHz, f_fnco={f_fnco} GHz",
                stacklevel=2,
            )
        return f_diff  # GHz

    @classmethod
    def calc_modulation_frequency(
        cls,
        f_target: float,
        port_config: PortConfigAcquirer,
    ) -> float:
        """
        Calculate modulation frequency from target frequency and port configuration.

        Parameters
        ----------
        f_target : float
            Target frequency in GHz.
        port_config : PortConfigAcquirer
            Port configuration.

        Returns
        -------
        float
            Modulation frequency in GHz.
        """
        # Note that port_config has frequencies in Hz.
        if port_config.lo_freq is None:
            return cls.calc_modulation_frequency_for_direct_conversion_transceiver(
                f_target=f_target,
                port_config=port_config,
            )
        f_lo = port_config.lo_freq * 1e-9  # Hz -> GHz
        f_cnco = port_config.cnco_freq * 1e-9  # Hz -> GHz
        f_fnco = port_config.fnco_freq * 1e-9  # Hz -> GHz
        sideband = port_config.sideband

        if port_config.dump_config["direction"] == "out":
            f_diff = cls._calc_modulation_frequency(
                target_freq=f_target,
                lo_freq=f_lo,
                cnco_freq=f_cnco,
                fnco_freq=f_fnco,
                sideband=sideband,
            )

            if abs(f_diff) > 0.5:
                p = port_config
                warnings.warn(
                    f"Modulation frequency abs({f_diff}) of {p.box_name}:{p.port}:{p.channel} is too high. f_target={f_target} GHz, f_lo={f_lo} GHz, f_cnco={f_cnco} GHz, f_fnco={f_fnco} GHz, sideband={sideband}",
                    stacklevel=2,
                )
        elif port_config.dump_config["direction"] == "in":
            opposite = "L" if sideband == "U" else "U"
            f_diff = cls._calc_modulation_frequency(
                target_freq=f_target,
                lo_freq=f_lo,
                cnco_freq=f_cnco,
                fnco_freq=f_fnco,
                sideband=sideband,
            )
            o_f_diff = cls._calc_modulation_frequency(
                target_freq=f_target,
                lo_freq=f_lo,
                cnco_freq=f_cnco,
                fnco_freq=f_fnco,
                sideband=opposite,
            )
            mindiff = f_diff if abs(f_diff) < abs(o_f_diff) else o_f_diff
            if abs(mindiff) > 0.25:
                p = port_config
                warnings.warn(
                    f"Modulation frequency abs({mindiff}) of {p.box_name}:{p.port}:{p.channel} is too high. f_target={f_target} GHz, f_lo={f_lo} GHz, f_cnco={f_cnco} GHz, f_fnco={f_fnco} GHz, sideband={sideband}",
                    stacklevel=2,
                )
        else:
            raise ValueError(f"{port_config} invalid direction")

        return f_diff  # GHz

    @classmethod
    def _calc_modulation_frequency(
        cls,
        target_freq: float,
        lo_freq: float,
        cnco_freq: float,
        fnco_freq: float,
        sideband: str,
    ) -> float:
        """Calculate modulation frequency from target frequency and port configuration."""
        # Note that port_config has frequencies in Hz.
        if sideband == Sideband.UpperSideBand.value:
            f_diff = target_freq - lo_freq - (cnco_freq + fnco_freq)
        elif sideband == Sideband.LowerSideBand.value:
            f_diff = -(target_freq - lo_freq) - (cnco_freq + fnco_freq)
        else:
            raise ValueError("invalid ssb mode")

        return f_diff  # GHz

    @classmethod
    def multiplex(
        cls,
        sequences: MutableMapping[str, GenSampledSequence],
        modfreqs: MutableMapping[str, float],
    ) -> GenSampledSequence:
        """Collapse multiple target waveforms into one multiplexed sequence."""
        cls.validate_geometry_identity(sequences)
        if not cls.validate_geometry_identity(sequences):
            raise ValueError(
                "All geometry of sub sequences belonging to the same awg must be equal"
            )
        sequence = sequences[next(iter(sequences))]
        padding = sequence.padding

        chain = {
            target_name: _convert_gen_sampled_sequence_to_blanks_and_waves_chain(subseq)
            for target_name, subseq in sequences.items()
        }
        begins = {
            target_name: [
                sum(chain[target_name][: i + 1])
                for i, _ in enumerate(chain[target_name][1:])
            ]
            for target_name in sequences
        }
        SAMPLING_PERIOD = sequence.sampling_period
        times = {
            target_name: [
                (begin + np.arange(subseq.real.shape[0]) - padding) * SAMPLING_PERIOD
                for begin, subseq in zip(
                    begins[target_name][::2],
                    sequence.sub_sequences,
                    strict=False,
                )
            ]
            for target_name, sequence in sequences.items()
        }
        waves = [
            np.array(
                [
                    (
                        sequences[target].sub_sequences[i].real
                        + 1j * sequences[target].sub_sequences[i].imag
                    )
                    * np.exp(1j * 2 * np.pi * (modfreqs[target] * times[target][i]))
                    for target in sequences
                ]
            ).sum(axis=0)
            for i, _ in enumerate(sequence.sub_sequences)
        ]

        return GenSampledSequence(
            target_name="",
            prev_blank=sequence.prev_blank,
            post_blank=sequence.post_blank,
            repeats=sequence.repeats,
            sampling_period=sequence.sampling_period,
            sub_sequences=[
                GenSampledSubSequence(
                    real=np.real(waves[i]),
                    imag=np.imag(waves[i]),
                    post_blank=subseq.post_blank,
                    repeats=subseq.repeats,
                )
                for i, subseq in enumerate(sequence.sub_sequences)
            ],
        )

    @classmethod
    def validate_geometry_identity(
        cls,
        sequences: MutableMapping[str, GenSampledSequence],
    ) -> bool:
        """Validate that all sequence geometries are mutually consistent."""
        _ = {
            target_name: [
                (_.real.shape, _.imag.shape, _.post_blank, _.repeats)
                for _ in sequence.sub_sequences
            ]
            for target_name, sequence in sequences.items()
        }
        return all(
            functools.reduce(
                operator.iadd,
                [[geometry[0] == __ for __ in geometry] for _, geometry in _.items()],
                [],
            )
        )


class Command:
    """Define the interface for executable command objects."""

    def execute(
        self,
        boxpool: BoxPool,
    ) -> Any:
        """Run the command against a runtime box pool."""
        pass


class TargetBPC(TypedDict):
    """Describe target mapping with box, port, and channel metadata."""

    box: Quel1BoxWithRawWss
    port: int | tuple[int, int]
    channel: int
    box_name: str


class PortConfigAcquirer:
    """Collect port configuration fields used by sequence conversion."""

    def __init__(
        self,
        boxpool: BoxPool,
        box_name: str,
        box: Quel1BoxWithRawWss,
        port: Quel1PortType,
        channel: int,
        *,
        driver: direct.Quel1System | None = None,
    ):
        if driver is None:
            # Reuse cached port dump to keep capture/generation conversions cheap.
            dump_box = boxpool.ensure_box_config_cache(
                box_name=box_name,
                box=box,
            )["ports"]
            self.dump_config = dp = dump_box[port]
            sideband = dp.get("sideband", DEFAULT_SIDEBAND)
            fnco_freq = 0
            if port in box.get_output_ports():
                fnco_freq = dp["channels"][channel]["fnco_freq"]
            if port in box.get_input_ports():
                fnco_freq = dp["runits"][channel]["fnco_freq"]
                if (
                    port in box.get_read_input_ports()
                    or port in box.get_monitor_input_ports()
                ):
                    lpbackps = box.get_loopbacks_of_port(port)
                    if lpbackps:
                        lpbackp = next(iter(lpbackps))
                        dumped_port = dump_box[lpbackp]
                        sideband = dumped_port.get("sideband", DEFAULT_SIDEBAND)
            self.lo_freq: float | None = dp.get("lo_freq", None)
            self.cnco_freq: float = dp["cnco_freq"]
            self.fnco_freq: float = fnco_freq
            self.sideband: str = sideband
        else:
            self.dump_config = driver.dump_port(box_name, port)
            self.lo_freq = driver.get_lo_freq(box_name, port)
            self.cnco_freq = driver.get_cnco_freq(box_name, port)
            self.fnco_freq = driver.get_fnco_freq(box_name, port, channel)
            sideband = driver.get_sideband(box_name, port)
            self.sideband = sideband if sideband is not None else DEFAULT_SIDEBAND
        self.box_name = box_name
        self.port = port
        self.channel = channel

    def __repr__(self) -> str:
        """Return a debug representation of acquired port settings."""
        return f"{self.__class__.__name__}(lo_freq={self.lo_freq}, cnco_freq={self.cnco_freq}, fnco_freq={self.fnco_freq}, sideband={self.sideband})"


class RfSwitch(Command):
    """Command that applies RF switch state changes."""

    def __init__(self, box_name: str, port: int, rfswitch: str):
        self._box_name = box_name
        self._port = port
        self._rfswitch = rfswitch

    def execute(
        self,
        boxpool: BoxPool,
    ) -> None:
        """Apply RF switch configuration to a target box port."""
        box = boxpool.get_box(self._box_name)[0]
        box.config_rfswitch(self._port, rfswitch=self._rfswitch)


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
        line_param0: tuple[float, float, float] = (1, 0, 0),
        line_param1: tuple[float, float, float] = (0, 1, 0),
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
        self.line_param0 = line_param0
        self.line_param1 = line_param1

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
                line_param0=self.line_param0,
                line_param1=self.line_param1,
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
        results: dict[tuple[str, Quel1PortType, int], npt.NDArray[np.complex64]],
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
        data: npt.NDArray[np.complex64],
        cprm: CaptureParam,
    ) -> tuple[CaptureReturnCode, list[npt.NDArray[np.complex64]]]:
        # num_expected_words = cprm.calc_capture_samples()
        """Parse one capture payload according to capture parameters."""
        if DspUnit.INTEGRATION in cprm.dsp_units_enabled:
            data = data.reshape(1, -1)
        else:
            data = data.reshape(cprm.num_integ_sections, -1)
        if DspUnit.SUM in cprm.dsp_units_enabled:
            width = len(cprm.sum_section_list)
            result = np.hsplit(data, width)
        else:
            b = DspUnit.DECIMATION not in cprm.dsp_units_enabled
            ssl = cprm.sum_section_list
            ws = [w if b else int(w // 4) for w, _ in ssl[:-1]]
            word = cprm.NUM_SAMPLES_IN_ADC_WORD
            width = np.cumsum(np.array(ws))
            result = np.hsplit(data, width * word)
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
