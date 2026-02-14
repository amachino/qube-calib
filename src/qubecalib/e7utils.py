"""Utilities for converting sampled sequences to e7-compatible parameters."""

from __future__ import annotations

import math
import sys
from itertools import pairwise

import numpy as np

from .e7compat import CaptureParam, DspUnit, IqWave, WaveSequence
from .neopulse import CapSampledSequence, GenSampledSequence

SAMPLING_PERIOD = 2

# Capture delay starts at the head of an input block (64 samples in e7awgsw).
# Since 1 capture word = 4 samples, pre-blank alignment becomes 16 words.
CAPTURE_PRE_BLANK_ALIGNMENT_WORDS = 16


class WaveSequenceTools:
    """Helpers that convert generator sampled sequences into `WaveSequence`."""

    @classmethod
    def create(
        cls,
        sequence: GenSampledSequence,
        wait_words: int,
        repeats: int,
        interval_samples: int,
    ) -> WaveSequence:
        """
        Convert one generator sampled sequence into a hardware `WaveSequence`.

        The conversion normalizes time units from samples to AWG words and
        delegates waveform packing and chunk creation to
        `create_single_chunked_wave_sequence`.

        Parameters
        ----------
        sequence : GenSampledSequence
            Source sampled waveform sequence for one logical target.
        wait_words : int
            Initial wait length in AWG words before waveform emission.
        repeats : int
            Fallback repeat count when `sequence.repeats` is `None`.
        interval_samples : int
            Total interval length in samples.

        Returns
        -------
        WaveSequence
            Converted one-chunk wave sequence compatible with legacy e7 APIs.
        """
        unit = WaveSequence.NUM_SAMPLES_IN_AWG_WORD
        return cls.create_single_chunked_wave_sequence(
            sequence=sequence,
            wait_words=wait_words,
            repeats=repeats,
            # NOTE: Int truncates toward shorter intervals when not word-aligned.
            # Effective interval can shrink by up to (unit - 1) samples.
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
        """
        Build a single-chunk `WaveSequence` from a generator sampled sequence.

        The method flattens `[blank, wave, blank, ...]` timing into absolute
        boundaries, writes each subsequence into one dense IQ buffer, converts it
        to the legacy packed format, and appends one chunk with post-blank chosen
        to satisfy `interval_words`.

        Parameters
        ----------
        sequence : GenSampledSequence
            Source sampled sequence.
        wait_words : int
            Initial wait length in AWG words.
        repeats : int
            Fallback repeat count when `sequence.repeats` is `None`.
        interval_words : int
            Target interval length in AWG words.

        Returns
        -------
        WaveSequence
            Wave sequence with exactly one chunk.

        Raises
        ------
        ValueError
            Raised when any IQ sample magnitude exceeds 1.
        """
        chain = _convert_gen_sampled_sequence_to_blanks_and_waves_chain(sequence)
        bounds = [sum(chain[: i + 1]) for i, _ in enumerate(chain)]
        i = np.zeros(bounds[-1], dtype=int)
        q = np.zeros(bounds[-1], dtype=int)
        epsilon = sys.float_info.epsilon
        # NOTE: `bounds[::2]` includes one extra terminal boundary
        # (end of the final blank), so drop the tail.
        for begin, subseq in zip(bounds[::2][:-1], sequence.sub_sequences, strict=True):
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
            # NOTE: If `interval_words` came from floor conversion, this blank
            # is computed against the shortened interval definition.
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
        """
        Convert one capture sampled sequence into legacy `CaptureParam`.

        This conversion maps sample-domain capture slots to ADC-word-domain
        sections, applies required boundary alignment, restores interval-length
        consistency, and enforces hardware constraints such as non-zero
        post-blank words.

        Parameters
        ----------
        sequence : CapSampledSequence
            Source capture sampled sequence for one logical target.
        capture_delay_words : int
            Additional delay (ADC words) applied before the first section.
        repeats : int
            Number of integration sections.
        interval_samples : int
            Total interval length in samples.

        Returns
        -------
        CaptureParam
            Capture parameter object compatible with legacy e7 APIs.

        Raises
        ------
        ValueError
            Raised when an aligned section would become too short to keep
            post-blank constraints (`Capture is too short`).
        """
        unit = CaptureParam.NUM_SAMPLES_IN_ADC_WORD
        chain = _convert_cap_sampled_sequence_to_blanks_and_durations_chain(sequence)
        chain[0] += sequence.padding
        bounds = [sum(chain[:i]) for i, _ in enumerate(chain)]
        aligned: list[int] = [
            0,
            # NOTE: Pre-blank is aligned to a 64-sample block boundary
            # (16 capture words) before capture starts.
            math.floor(bounds[1] / (CAPTURE_PRE_BLANK_ALIGNMENT_WORDS * unit))
            * CAPTURE_PRE_BLANK_ALIGNMENT_WORDS
            * unit,
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
                # NOTE: Hardware requires post-blank >= 1 word for every section.
                # Keep boundaries almost unchanged by borrowing 1 word:
                # (d, 0) -> (d - 1, 1).
                # This shortens the previous integration window by 1 word
                # (4 samples, 8 ns). If this is the last blank, only the
                # final integration window becomes 1 word shorter.
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
    """
    Convert a generator sequence into a `[blank, wave, blank, ...]` chain.

    Parameters
    ----------
    sequence : GenSampledSequence
        Source generator sampled sequence.

    Returns
    -------
    list[int]
        Alternating blank/wave lengths in samples. The first element is the
        leading blank and the last element is the trailing blank.
    """
    chain: list[int] = [sequence.prev_blank]
    for subseq in sequence.sub_sequences[:-1]:
        # NOTE: `None` is treated as no additional blank (0).
        # This makes "unset" and explicit zero equivalent here.
        chain.extend([subseq.real.shape[0], subseq.post_blank or 0])
    last_subseq = sequence.sub_sequences[-1]
    last_blank = (
        last_subseq.post_blank + sequence.post_blank
        if sequence.post_blank is not None and last_subseq.post_blank is not None
        # NOTE: Same permissive fallback as above.
        # Missing tail blank metadata is normalized to zero.
        else 0
    )
    chain.extend([last_subseq.real.shape[0], last_blank])
    return chain


def _convert_cap_sampled_sequence_to_blanks_and_durations_chain(
    sequence: CapSampledSequence,
) -> list[int]:
    """
    Convert a capture sequence into a `[blank, duration, blank, ...]` chain.

    The conversion merges nested blank contributors (slot/subsequence/top-level)
    into bridge blanks between capture durations.

    Parameters
    ----------
    sequence : CapSampledSequence
        Source capture sampled sequence.

    Returns
    -------
    list[int]
        Alternating blank/duration lengths in samples.

    Raises
    ------
    ValueError
        Raised when any required blank value is missing.
    """
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
    last_blank = (
        _require_int(
            seq.sub_sequences[-1].capture_slots[-1].post_blank
            + seq.sub_sequences[-1].post_blank
            + seq.post_blank
            if seq.sub_sequences[-1].capture_slots[-1].post_blank is not None
            and seq.sub_sequences[-1].post_blank is not None
            else None,
            context="last blank",
        )
        # NOTE: Legacy behavior allows missing top-level tail blank by
        # normalizing to zero; later alignment/constraint logic repairs
        # the final shape.
        if seq.post_blank is not None
        else 0
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
    """
    Convert capture timing to a chain using original (pre-rounding) values.

    Parameters
    ----------
    sequence : CapSampledSequence
        Source capture sampled sequence.

    Returns
    -------
    list[int]
        Alternating blank/duration lengths computed from original values and
        cast to integers.

    Raises
    ------
    ValueError
        Raised when required original blank fields are missing.
    """
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
