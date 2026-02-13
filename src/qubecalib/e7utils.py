"""Utilities for converting sampled sequences to e7-compatible parameters."""

from __future__ import annotations

import math
import sys
from collections.abc import MutableMapping
from itertools import pairwise
from typing import Any

import numpy as np

from .e7compat import CaptureParam, DspUnit, IqWave, WaveSequence
from .neopulse import CapSampledSequence, GenSampledSequence

SAMPLING_PERIOD = 2


class WaveSequenceTools:
    """Helpers that convert generator sampled sequences into `WaveSequence`."""

    @classmethod
    def quantize_duration(
        cls,
        duration: float,
        constrain: int = 10_240,
    ) -> int:
        """Quantize duration to a hardware-friendly period."""
        return int(duration // constrain) * constrain

    @classmethod
    def validate_e7_compatibility(
        cls,
        sequences: MutableMapping[str, GenSampledSequence],
    ) -> bool:
        """Return whether all sequences satisfy legacy e7 constraints."""
        _ = sequences
        return False

    @classmethod
    def create_chunk(cls) -> MutableMapping[str, Any]:
        """Return an empty legacy chunk container."""
        return {}

    @classmethod
    def create(
        cls,
        sequence: GenSampledSequence,
        wait_words: int,
        repeats: int,
        interval_samples: int,
    ) -> WaveSequence:
        """Create a `WaveSequence` from a sampled generator sequence."""
        unit = WaveSequence.NUM_SAMPLES_IN_AWG_WORD
        return cls.create_single_chunked_wave_sequence(
            sequence=sequence,
            wait_words=wait_words,
            repeats=repeats,
            interval_words=int(interval_samples / unit),
        )

    @classmethod
    def create_single_chunked_wave_sequence(
        cls,
        sequence: GenSampledSequence,
        wait_words: int,
        repeats: int,
        interval_words: int,
    ) -> WaveSequence:
        """Create one-wavechunk `WaveSequence` from the given generator sequence."""
        chain = _convert_gen_sampled_sequence_to_blanks_and_waves_chain(sequence)
        bounds = [sum(chain[: i + 1]) for i, _ in enumerate(chain)]
        i = np.zeros(bounds[-1], dtype=int)
        q = np.zeros(bounds[-1], dtype=int)
        epsilon = sys.float_info.epsilon
        for begin, subseq in zip(bounds[::2], sequence.sub_sequences, strict=True):
            if (
                max(np.abs(subseq.real)) - 1 > epsilon
                or max(np.abs(subseq.imag)) - 1 > epsilon
            ):
                raise ValueError("magnitude of iq signal must not exceed 1")
            i[begin : begin + subseq.real.shape[0]] = (32767 * subseq.real).astype(int)
            q[begin : begin + subseq.imag.shape[0]] = (32767 * subseq.imag).astype(int)
        wseq = WaveSequence(
            num_wait_words=wait_words,
            num_repeats=sequence.repeats if sequence.repeats is not None else repeats,
        )

        s = IqWave.convert_to_iq_format(i, q, WaveSequence.NUM_SAMPLES_IN_WAVE_BLOCK)
        total_duration_in_words = int(len(s) // WaveSequence.NUM_SAMPLES_IN_AWG_WORD)
        wseq.add_chunk(
            iq_samples=s,
            num_blank_words=interval_words - total_duration_in_words,
            num_repeats=1,
        )
        return wseq


class CaptureParamTools:
    """Helpers that convert capture sampled sequences into `CaptureParam`."""

    @classmethod
    def create(
        cls,
        sequence: CapSampledSequence,
        capture_delay_words: int,
        repeats: int,
        interval_samples: int,
    ) -> CaptureParam:
        """Create a `CaptureParam` aligned to hardware constraints."""
        unit = CaptureParam.NUM_SAMPLES_IN_ADC_WORD
        chain = _convert_cap_sampled_sequence_to_blanks_and_durations_chain(sequence)
        chain[0] += sequence.padding
        bounds = [sum(chain[:i]) for i, _ in enumerate(chain)]
        aligned: list[int] = [
            0,
            math.floor(bounds[1] / (16 * unit)) * 16 * unit,
        ] + [math.floor(bound / unit) * unit for bound in bounds[2:]]
        new_chain = [int((up - low) / unit) for low, up in pairwise(aligned)] + [
            int(chain[-1])
        ]
        total_duration_words = sum(new_chain)
        interval_words = int(interval_samples // unit)
        new_chain[-1] = interval_words - total_duration_words + new_chain[0]
        for i in range(2, len(new_chain), 2):
            if new_chain[i] == 0:
                if new_chain[i - 1] == 1:
                    raise ValueError("Capture is too short")
                new_chain[i - 1] -= 1
                new_chain[i] = 1
        capprm = CaptureParam()
        capprm.capture_delay = capture_delay_words + new_chain[0]
        capprm.num_integ_sections = repeats
        for duration, blank in zip(new_chain[1::2], new_chain[2::2], strict=True):
            capprm.add_sum_section(
                num_words=duration,
                num_post_blank_words=blank,
            )

        return capprm

    @classmethod
    def enable_integration(
        cls,
        capprm: CaptureParam,
    ) -> CaptureParam:
        """Enable integration DSP in the given capture parameter."""
        dsp = capprm.dsp_units_enabled
        dsp.append(DspUnit.INTEGRATION)
        capprm.sel_dsp_units_to_enable(*dsp)
        return capprm

    @classmethod
    def enable_sum(
        cls,
        capprm: CaptureParam,
    ) -> CaptureParam:
        """Enable sum DSP in the given capture parameter."""
        dsp = capprm.dsp_units_enabled
        dsp.append(DspUnit.SUM)
        capprm.sel_dsp_units_to_enable(*dsp)
        return capprm

    @classmethod
    def enable_demodulation(
        cls,
        capprm: CaptureParam,
        f_GHz: float,
    ) -> CaptureParam:
        """
        Enable demodulation of the captured signal.

        Parameters
        ----------
        capprm : CaptureParam
            Capture parameters.
        f_GHz : float
            Frequency in GHz to demodulate the captured signal.

        Returns
        -------
        CaptureParam
            CaptureParam object with demodulation enabled.
        """
        capprm.complex_fir_coefs = cls.fir_coefficient(f_GHz)
        capprm.complex_window_coefs = cls.window_coefficient(f_GHz)

        dspunits = capprm.dsp_units_enabled
        dspunits.append(DspUnit.COMPLEX_FIR)
        dspunits.append(DspUnit.DECIMATION)
        dspunits.append(DspUnit.COMPLEX_WINDOW)
        capprm.sel_dsp_units_to_enable(*dspunits)
        return capprm

    @classmethod
    def fir_coefficient(
        cls,
        f_GHz: float,
    ) -> list[complex]:
        """
        Calculate FIR coefficients for a bandpass filter.

        Parameters
        ----------
        f_GHz : float
            Center frequency of the bandpass filter in GHz.

        Returns
        -------
        list[complex]
            FIR coefficients for the bandpass filter.
            Each part of a complex FIR coefficient must be an integer
            and in the range of [-2**15, 2**15 - 1].
        """
        N_COEFS = CaptureParam.NUM_COMPLEX_FIR_COEFS  # 16
        MAX_VAL = CaptureParam.MAX_FIR_COEF_VAL  # 32767
        t_ns = SAMPLING_PERIOD * np.arange(-N_COEFS + 1, 1)  # [-30, -28, ..., 0]

        # rect window
        # window_function = MAX_VAL * np.ones(N_COEFS).astype(complex)

        # gaussian window
        mu = (t_ns[-1] + t_ns[0]) / 2
        sigma = (t_ns[-1] - t_ns[0]) / 6
        window_function = MAX_VAL * np.exp(-0.5 * (t_ns - mu) ** 2 / (sigma**2))

        coefs = window_function * np.exp(1j * 2 * np.pi * f_GHz * t_ns)
        result = coefs.round().tolist()
        return result

    @classmethod
    def window_coefficient(
        cls,
        f_GHz: float,
    ) -> list[complex]:
        """
        Calculate window coefficients for a bandpass filter.

        Parameters
        ----------
        f_GHz : float
            Center frequency of the bandpass filter in GHz.

        Returns
        -------
        list[complex]
            Window coefficients for the bandpass filter.
            Each part of a complex window coefficient must be an integer
            and in the range of [-2**31, 2**31 - 1].
        """
        N_DECIMATION = 4
        N_COEFS = CaptureParam.NUM_COMPLEXW_WINDOW_COEFS  # 2048
        MAX_VAL = CaptureParam.MAX_WINDOW_COEF_VAL  # 2147483647
        t_ns = N_DECIMATION * SAMPLING_PERIOD * np.arange(N_COEFS)  # [0, 8, ..., 16376]
        coefs = MAX_VAL * np.exp(-1j * 2 * np.pi * f_GHz * t_ns)
        result = coefs.round().tolist()
        return result

    @classmethod
    def enable_classification(
        cls,
        capprm: CaptureParam,
        *,
        line_param0: tuple[float, float, float],
        line_param1: tuple[float, float, float],
    ) -> CaptureParam:
        """
        Enable classification in the capture parameters.

        Parameters
        ----------
        capprm : CaptureParam
            Capture parameters.

        Returns
        -------
        CaptureParam
            CaptureParam object with classification enabled.
        """
        dspunits = capprm.dsp_units_enabled
        dspunits.append(DspUnit.CLASSIFICATION)
        capprm.sel_dsp_units_to_enable(*dspunits)
        capprm.set_decision_func_params(
            func_sel=0,
            coef_a=np.float32(line_param0[0]),
            coef_b=np.float32(line_param0[1]),
            const_c=np.float32(line_param0[2]),
        )
        capprm.set_decision_func_params(
            func_sel=1,
            coef_a=np.float32(line_param1[0]),
            coef_b=np.float32(line_param1[1]),
            const_c=np.float32(line_param1[2]),
        )

        return capprm


def _convert_gen_sampled_sequence_to_blanks_and_waves_chain(
    sequence: GenSampledSequence,
) -> list[int]:
    """Convert generator sampled sequence to `[blank, wave, blank, ...]` chain."""
    chain: list[int] = [sequence.prev_blank]
    for subseq in sequence.sub_sequences[:-1]:
        chain.extend([subseq.real.shape[0], subseq.post_blank or 0])
    last_subseq = sequence.sub_sequences[-1]
    last_blank = (
        last_subseq.post_blank + sequence.post_blank
        if sequence.post_blank is not None and last_subseq.post_blank is not None
        else 0
    )
    chain.extend([last_subseq.real.shape[0], last_blank])
    return chain


def _convert_cap_sampled_sequence_to_blanks_and_durations_chain(
    sequence: CapSampledSequence,
) -> list[int]:
    """Convert capture sampled sequence to `[blank, duration, blank, ...]` chain."""
    seq = sequence
    blank_bridges = [
        _require_int(
            lo.capture_slots[-1].post_blank + lo.post_blank + hi.prev_blank
            if lo.capture_slots[-1].post_blank is not None
            and lo.post_blank is not None
            and hi.prev_blank is not None
            else None,
            context="blank bridge",
        )
        for lo, hi in zip(seq.sub_sequences[:-1], seq.sub_sequences[1:], strict=True)
    ]
    last_blank = _require_int(
        seq.sub_sequences[-1].capture_slots[-1].post_blank
        + seq.sub_sequences[-1].post_blank
        + seq.post_blank
        if seq.sub_sequences[-1].capture_slots[-1].post_blank is not None
        and seq.sub_sequences[-1].post_blank is not None
        and seq.post_blank is not None
        else None,
        context="last blank",
    )
    chain: list[int] = [seq.prev_blank + seq.sub_sequences[0].prev_blank]
    for subseq, blank in zip(seq.sub_sequences[:-1], blank_bridges, strict=True):
        for slot in subseq.capture_slots[:-1]:
            chain.extend(
                [slot.duration, _require_int(slot.post_blank, context="slot blank")]
            )
        chain.extend([subseq.capture_slots[-1].duration, blank])
    for slot in seq.sub_sequences[-1].capture_slots[:-1]:
        chain.extend(
            [slot.duration, _require_int(slot.post_blank, context="slot blank")]
        )
    chain.extend([seq.sub_sequences[-1].capture_slots[-1].duration, last_blank])
    return chain


def _convert_cap_sampled_sequence_to_blanks_and_durations_chain_use_original_values(
    sequence: CapSampledSequence,
) -> list[int]:
    """Convert capture sampled sequence chain using original-duration values."""
    seq = sequence
    blank_bridges = [
        _require_int(
            lo.capture_slots[-1].original_post_blank
            + lo.original_post_blank
            + hi.original_prev_blank
            if lo.capture_slots[-1].original_post_blank is not None
            and lo.original_post_blank is not None
            and hi.original_prev_blank is not None
            else None,
            context="original blank bridge",
        )
        for lo, hi in zip(seq.sub_sequences[:-1], seq.sub_sequences[1:], strict=True)
    ]
    last_blank = _require_int(
        seq.sub_sequences[-1].capture_slots[-1].original_post_blank
        + seq.sub_sequences[-1].original_post_blank
        + seq.original_post_blank
        if seq.sub_sequences[-1].capture_slots[-1].original_post_blank is not None
        and seq.sub_sequences[-1].original_post_blank is not None
        and seq.original_post_blank is not None
        else None,
        context="original last blank",
    )

    prev_blank = seq.original_prev_blank
    if prev_blank is None:
        raise ValueError("original_prev_blank must be set")
    subseq_prev_blank = seq.sub_sequences[0].original_prev_blank
    if subseq_prev_blank is None:
        raise ValueError("original_prev_blank of subseq must be set")

    chain: list[int] = [int(prev_blank + subseq_prev_blank)]
    for subseq, blank in zip(seq.sub_sequences[:-1], blank_bridges, strict=True):
        for slot in subseq.capture_slots[:-1]:
            chain.extend(
                [
                    int(slot.original_duration),
                    _require_int(
                        slot.original_post_blank, context="original slot blank"
                    ),
                ]
            )
        chain.extend([int(subseq.capture_slots[-1].original_duration), blank])
    for slot in seq.sub_sequences[-1].capture_slots[:-1]:
        chain.extend(
            [
                int(slot.original_duration),
                _require_int(slot.original_post_blank, context="original slot blank"),
            ]
        )
    chain.extend(
        [int(seq.sub_sequences[-1].capture_slots[-1].original_duration), last_blank]
    )
    return chain


def _require_int(value: int | float | None, *, context: str) -> int:
    """Return integer value or raise when missing."""
    if value is None:
        raise ValueError(f"{context} must be set")
    return int(value)
