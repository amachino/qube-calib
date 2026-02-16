"""Waveform conversion helpers for QuEL sequencer execution."""

from __future__ import annotations

import logging
import math
from collections import Counter
from collections.abc import MutableMapping
from copy import deepcopy
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

from qxdriver_quel.e7awg.compat import CaptureParam, WaveSequence
from qxdriver_quel.e7awg.utils import (
    CaptureParamTools,
    WaveSequenceTools,
    _convert_gen_sampled_sequence_to_blanks_and_waves_chain,
)
from qxdriver_quel.pulse import (
    CapSampledSequence,
    GenSampledSequence,
    GenSampledSubSequence,
)
from qxdriver_quel.sysconf import (
    BoxSetting,
    PortSetting,
    Quel1PortType,
)

if TYPE_CHECKING:
    from qxdriver_quel.runtime.sequencer_core import PortConfigAcquirer

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
SAMPLING_PERIOD_NS = 2.0

# Sampled waveforms are represented at 2 ns steps (500 MS/s), so the modulation
# term must stay within the Nyquist band (+/- 250 MHz) to avoid aliasing.
MAX_MODULATION_FREQUENCY_GHZ = 0.25


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
        cap_targets = set(cap_sampled_sequence)
        gen_targets = set(gen_sampled_sequence)
        capseq = cls.convert_to_cap_device_specific_sequence(
            gen_sampled_sequence=gen_sampled_sequence,
            cap_sampled_sequence=cap_sampled_sequence,
            resource_map={
                target_name: mapping
                for target_name, mapping in resource_map.items()
                if target_name in cap_targets
            },
            port_config={
                target_name: config
                for target_name, config in port_config.items()
                if target_name in cap_targets
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
                target_name: mapping
                for target_name, mapping in resource_map.items()
                if target_name in gen_targets
            },
            port_config={
                target_name: config
                for target_name, config in port_config.items()
                if target_name in gen_targets
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
        # Work on a detached copy to keep caller-owned sampled sequences immutable.
        working_gen_sequences = {
            target_name: cls._clone_gen_sampled_sequence(sequence)
            for target_name, sequence in gen_sampled_sequence.items()
        }

        targets_freqs: dict[str, float] = {}
        targets_ids: dict[str, tuple[str, Quel1PortType, int]] = {}
        for target_name, rmap in resource_map.items():
            rmap_target = rmap["target"]
            if not isinstance(rmap_target, dict):
                raise TypeError("target is not defined")
            targets_freqs[target_name] = cls.calc_modulation_frequency(
                f_target=rmap_target["frequency"],
                port_config=port_config[target_name],
            )
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
            working_gen_sequences[target_name].modulation_frequency = freq
        for target_name, gen_sequence in working_gen_sequences.items():
            if target_name not in cap_sampled_sequence:
                continue
            modulation_angular_frequency = 2 * np.pi * targets_freqs[target_name]
            timing_list = gen_sequence.readout_timings
            offset_list = cap_sampled_sequence[target_name].readin_offsets
            if timing_list is None and offset_list is None:
                continue
            if timing_list is None:
                raise ValueError("readout_timings is not defined")
            if offset_list is None:
                raise ValueError("readin_offsets is not defined")
            for subseq, timings, offsets in zip(
                gen_sequence.sub_sequences, timing_list, offset_list, strict=False
            ):
                # NOTE: `strict=False` tolerates length mismatches by truncation.
                # A mismatch can silently leave trailing subsequences uncorrected.
                wave = subseq.real + 1j * subseq.imag
                for (begin, end), (offsetb, _) in zip(timings, offsets, strict=False):
                    # NOTE: Same truncation caveat as above for timing/offset pairs.
                    offset_phase = modulation_angular_frequency * offsetb
                    b = math.floor(begin / SAMPLING_PERIOD_NS)
                    e = math.floor(end / SAMPLING_PERIOD_NS)
                    wave[b:e] = wave[b:e] * np.exp(-1j * offset_phase)
                subseq.real = np.real(wave)
                subseq.imag = np.imag(wave)

        ndelay_or_nwait_by_id = {
            (
                rmap_box.box_name,
                rmap_port.port,
                rmap_channel_number,
            ): (
                rmap_port.ndelay_or_nwait[rmap_channel_number]
                if rmap_port.ndelay_or_nwait is not None
                else 0
            )
            for rmap in resource_map.values()
            if isinstance(rmap["box"], BoxSetting)
            and isinstance(rmap["port"], PortSetting)
            and isinstance(rmap["channel_number"], int)
            for rmap_box, rmap_port, rmap_channel_number in [
                (
                    rmap["box"],
                    rmap["port"],
                    rmap["channel_number"],
                )
            ]
        }
        ids_sampled_sequences: dict[
            tuple[str, Quel1PortType, int], dict[str, GenSampledSequence]
        ] = {}
        for target_name, hardware_id in targets_ids.items():
            if target_name not in working_gen_sequences:
                continue
            if hardware_id not in ids_sampled_sequences:
                ids_sampled_sequences[hardware_id] = {}
            ids_sampled_sequences[hardware_id][target_name] = working_gen_sequences[
                target_name
            ]
        ids_modfreqs = {
            hardware_id: {
                target_name: targets_freqs[target_name]
                for target_name, target_hardware_id in targets_ids.items()
                if target_hardware_id == hardware_id
            }
            for hardware_id in targets_ids.values()
        }
        for sequence in working_gen_sequences.values():
            if sequence.padding == 0:
                continue
            first_subseq = sequence.sub_sequences[0]
            zeros = np.zeros(sequence.padding)
            first_subseq.real = np.concatenate([zeros, first_subseq.real])
            first_subseq.imag = np.concatenate([zeros, first_subseq.imag])
        ids_muxed_sequences = {
            hardware_id: cls.multiplex(
                sequences=ids_sampled_sequences[hardware_id],
                modfreqs=ids_modfreqs[hardware_id],
            )
            for hardware_id in ids_sampled_sequences
        }
        return {
            hardware_id: WaveSequenceTools.create(
                sequence=ids_muxed_sequences[hardware_id],
                wait_words=ndelay_or_nwait_by_id[hardware_id],
                repeats=repeats,
                interval_samples=int(
                    interval / ids_muxed_sequences[hardware_id].sampling_period
                ),
            )
            for hardware_id in ids_sampled_sequences
        }

    @staticmethod
    def _clone_gen_sampled_sequence(sequence: GenSampledSequence) -> GenSampledSequence:
        """Return a detached copy of one generator sampled sequence."""
        return GenSampledSequence(
            target_name=sequence.target_name,
            prev_blank=sequence.prev_blank,
            sampling_period=sequence.sampling_period,
            post_blank=sequence.post_blank,
            repeats=sequence.repeats,
            original_prev_blank=sequence.original_prev_blank,
            original_post_blank=sequence.original_post_blank,
            padding=sequence.padding,
            modulation_frequency=sequence.modulation_frequency,
            sub_sequences=[
                GenSampledSubSequence(
                    real=np.array(subseq.real, copy=True),
                    imag=np.array(subseq.imag, copy=True),
                    repeats=subseq.repeats,
                    post_blank=subseq.post_blank,
                    original_post_blank=subseq.original_post_blank,
                )
                for subseq in sequence.sub_sequences
            ],
            readout_timings=deepcopy(sequence.readout_timings),
        )

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
        if abs(f_diff) > MAX_MODULATION_FREQUENCY_GHZ:
            p = port_config
            logger.debug(
                "Modulation frequency abs(%s) of %s:%s:%s is too high. "
                "f_target=%s GHz, f_cnco=%s GHz, f_fnco=%s GHz",
                f_diff,
                p.box_name,
                p.port,
                p.channel,
                f_target,
                f_cnco,
                f_fnco,
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

            if abs(f_diff) > MAX_MODULATION_FREQUENCY_GHZ:
                p = port_config
                logger.debug(
                    "Modulation frequency abs(%s) of %s:%s:%s is too high. "
                    "f_target=%s GHz, f_lo=%s GHz, f_cnco=%s GHz, f_fnco=%s GHz, "
                    "sideband=%s",
                    f_diff,
                    p.box_name,
                    p.port,
                    p.channel,
                    f_target,
                    f_lo,
                    f_cnco,
                    f_fnco,
                    sideband,
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
            if abs(mindiff) > MAX_MODULATION_FREQUENCY_GHZ:
                p = port_config
                logger.debug(
                    "Modulation frequency abs(%s) of %s:%s:%s is too high. "
                    "f_target=%s GHz, f_lo=%s GHz, f_cnco=%s GHz, f_fnco=%s GHz, "
                    "sideband=%s",
                    mindiff,
                    p.box_name,
                    p.port,
                    p.channel,
                    f_target,
                    f_lo,
                    f_cnco,
                    f_fnco,
                    sideband,
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
                # NOTE: `strict=False` truncates on geometry mismatch between
                # computed begin indices and subsequences.
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
        geometries = [
            [
                (
                    subseq.real.shape,
                    subseq.imag.shape,
                    subseq.post_blank,
                    subseq.repeats,
                )
                for subseq in sequence.sub_sequences
            ]
            for sequence in sequences.values()
        ]
        if not geometries:
            return True
        reference_geometry = geometries[0]
        return all(geometry == reference_geometry for geometry in geometries[1:])
