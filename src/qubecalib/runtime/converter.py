"""Waveform conversion helpers for QuEL sequencer execution."""

from __future__ import annotations

import functools
import logging
import math
import operator
import warnings
from collections import Counter
from collections.abc import MutableMapping
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

from qubecalib.e7compat import CaptureParam, WaveSequence
from qubecalib.e7utils import (
    CaptureParamTools,
    WaveSequenceTools,
    _convert_gen_sampled_sequence_to_blanks_and_waves_chain,
)
from qubecalib.neopulse import (
    CapSampledSequence,
    GenSampledSequence,
    GenSampledSubSequence,
)
from qubecalib.sysconfdb import (
    BoxSetting,
    PortSetting,
    Quel1PortType,
)

if TYPE_CHECKING:
    from qubecalib.runtime.sequencer_core import PortConfigAcquirer

logger = logging.getLogger(__name__)


class Direction(Enum):
    """Define signal direction relative to logical targets."""

    FROM_TARGET = "from_target"
    TO_TARGET = "to_target"


class Sideband(Enum):
    """Define sideband labels used by mixer configuration."""

    UpperSideBand = "U"
    LowerSideBand = "L"


DEFAULT_SIDEBAND = "U"


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
        """
        Convert sampled sequences into per-device generation/capture settings.

        The method dispatches conversion to capture and generation pipelines,
        each filtered by target availability, and merges the resulting settings
        map keyed by `(box_name, port, channel_or_runit)`.

        Parameters
        ----------
        gen_sampled_sequence : dict[str, GenSampledSequence]
            Generator sampled sequences indexed by target name.
        cap_sampled_sequence : dict[str, CapSampledSequence]
            Capture sampled sequences indexed by target name.
        resource_map : dict[str, dict[str, BoxSetting | PortSetting | int | dict[str, float]]]
            Logical-to-physical resource mapping for each target.
        port_config : dict[str, PortConfigAcquirer]
            Port configuration indexed by target name.
        repeats : int
            Number of shot repeats used by conversion.
        interval : float
            Sequence interval in nanoseconds.
        integral_mode : str
            Integration mode selector for capture conversion.
        dsp_demodulation : bool
            Whether to enable hardware DSP demodulation.
        software_demodulation : bool
            Whether software demodulation is requested.
        enable_sum : bool
            Whether to enable SUM DSP.
        enable_classification : bool, default False
            Whether to enable classification DSP.
        line_param0 : tuple[float, float, float], default (1, 0, 0)
            Decision boundary parameter set 0 for classification.
        line_param1 : tuple[float, float, float], default (0, 1, 0)
            Decision boundary parameter set 1 for classification.

        Returns
        -------
        dict[tuple[str, Quel1PortType, int], WaveSequence | CaptureParam]
            Device-specific setting map for both AWG and capture units.
        """
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
        """
        Convert capture sampled sequences into per-runit `CaptureParam` objects.

        The conversion resolves modulation frequencies and hardware IDs,
        validates one-target-per-runit constraints, builds base `CaptureParam`
        values, and applies DSP options (integration/demodulation/sum/classifier)
        according to flags.

        Parameters
        ----------
        gen_sampled_sequence : dict[str, GenSampledSequence]
            Generator sampled sequences indexed by target name. This argument is
            accepted for API symmetry and currently not used directly.
        cap_sampled_sequence : dict[str, CapSampledSequence]
            Capture sampled sequences indexed by target name.
        resource_map : dict[str, dict[str, BoxSetting | PortSetting | int | dict[str, float]]]
            Logical-to-physical resource mapping for capture targets.
        port_config : dict[str, PortConfigAcquirer]
            Port configuration indexed by target name.
        repeats : int
            Number of integration repeats.
        interval : float
            Sequence interval in nanoseconds.
        integral_mode : str
            Integration mode selector (for example, `"integral"`).
        dsp_demodulation : bool
            Whether to enable capture DSP demodulation.
        software_demodulation : bool
            Whether software demodulation is requested.
        enable_sum : bool
            Whether to enable SUM DSP.
        enable_classification : bool, default False
            Whether to enable classification DSP.
        line_param0 : tuple[float, float, float], default (1, 0, 0)
            Decision boundary parameter set 0.
        line_param1 : tuple[float, float, float], default (0, 1, 0)
            Decision boundary parameter set 1.

        Returns
        -------
        dict[tuple[str, Quel1PortType, int], CaptureParam]
            Capture parameters keyed by physical runit identifier.

        Raises
        ------
        ValueError
            Raised when multiple targets are mapped to the same capture unit.
        """
        _ = gen_sampled_sequence
        _ = software_demodulation
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
        """
        Convert generator sampled sequences into per-AWG `WaveSequence` objects.

        The conversion resolves modulation frequency and physical IDs, applies
        readout phase offsets when capture offsets are available, groups targets
        by AWG channel, multiplexes grouped waveforms, and finally creates
        hardware-compatible `WaveSequence` values.

        Parameters
        ----------
        gen_sampled_sequence : dict[str, GenSampledSequence]
            Generator sampled sequences indexed by target name.
        cap_sampled_sequence : dict[str, CapSampledSequence]
            Capture sampled sequences used for optional readout offset alignment.
        resource_map : dict[str, dict[str, BoxSetting | PortSetting | int | dict[str, float]]]
            Logical-to-physical resource mapping for generator targets.
        port_config : dict[str, PortConfigAcquirer]
            Port configuration indexed by target name.
        repeats : int
            Repeat count used when building each `WaveSequence`.
        interval : float
            Sequence interval in nanoseconds.

        Returns
        -------
        dict[tuple[str, Quel1PortType, int], WaveSequence]
            Wave sequences keyed by physical AWG identifier.

        Raises
        ------
        TypeError
            Raised when required `resource_map` entries have invalid types.
        ValueError
            Raised when readout timing/offset metadata is partially missing.
        """
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
        """
        Multiplex multiple target waveforms into a single sampled sequence.

        All input sequences must share the same geometry. Each target waveform is
        up-converted by its modulation frequency and summed per subsequence in
        the time domain.

        Parameters
        ----------
        sequences : MutableMapping[str, GenSampledSequence]
            Generator sampled sequences to multiplex.
        modfreqs : MutableMapping[str, float]
            Modulation frequencies in GHz keyed by target name.

        Returns
        -------
        GenSampledSequence
            Multiplexed sampled sequence with combined complex waveform.

        Raises
        ------
        ValueError
            Raised when sequence geometries are not identical.
        """
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
