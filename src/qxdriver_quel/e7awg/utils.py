"""Utilities for converting sampled sequences to e7-compatible parameters."""

from __future__ import annotations

import math
import sys
from collections.abc import MutableSequence
from itertools import accumulate, pairwise

import numpy as np

from qxdriver_quel.e7awg.compat import CaptureParam, DspUnit, IqWave, WaveSequence
from qxdriver_quel.pulse import CapSampledSequence, CaptureSlots, GenSampledSequence

SAMPLING_PERIOD = 2
IQ_QUANTIZATION_SCALE = 32767

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
        # The AWG interface uses "words" as its time unit, so convert from samples.
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
        # Flatten once to get the total sample count including all blanks.
        chain = _convert_gen_sampled_sequence_to_blanks_and_waves_chain(sequence)
        total_samples = sum(chain)
        # Allocate integer buffers because samples are quantized before upload.
        i = np.zeros(total_samples, dtype=np.int32)
        q = np.zeros(total_samples, dtype=np.int32)
        # Small tolerance to ignore tiny floating-point overshoots around +/-1.
        epsilon = sys.float_info.epsilon
        # Walk through subsequences while tracking the absolute write offset.
        start = sequence.prev_blank
        for subseq in sequence.sub_sequences:
            # Input IQ is expected to be normalized to [-1, 1].
            if np.any(np.abs(subseq.real) > 1 + epsilon) or np.any(
                np.abs(subseq.imag) > 1 + epsilon
            ):
                raise ValueError("magnitude of iq signal must not exceed 1")
            stop = start + subseq.real.shape[0]
            # Quantize I/Q to DAC scale and write into the corresponding interval.
            # The cast to int32 happens on write because `out` points to int32 slices.
            np.multiply(
                subseq.real,
                IQ_QUANTIZATION_SCALE,
                out=i[start:stop],
                casting="unsafe",
            )
            np.multiply(
                subseq.imag,
                IQ_QUANTIZATION_SCALE,
                out=q[start:stop],
                casting="unsafe",
            )
            # Each subsequence contributes its own trailing blank.
            start = stop + (subseq.post_blank or 0)

        # Use sequence-level repeats when available; otherwise use the fallback.
        wseq = WaveSequence(
            num_wait_words=wait_words,
            num_repeats=sequence.repeats if sequence.repeats is not None else repeats,
        )

        # Convert to e7-compatible Nx2 IQ format and pad to a full wave block.
        s = IqWave.convert_to_iq_format(i, q, WaveSequence.NUM_SAMPLES_IN_WAVE_BLOCK)
        # `convert_to_iq_format` pads to wave-block boundaries (64 samples), and one
        # AWG word is 4 samples, so this division is exact (no ceil/floor ambiguity).
        total_duration_in_words = len(s) // WaveSequence.NUM_SAMPLES_IN_AWG_WORD
        wseq.add_chunk(
            iq_samples=s,
            # NOTE: If `interval_words` came from floor conversion, this blank
            # is computed against the shortened interval definition.
            # Treat interval as a lower bound for total chunk length.
            # If waveform packing exceeds the requested interval, clamp the
            # trailing blank to zero to keep chunk metadata valid.
            num_blank_words=max(0, interval_words - total_duration_in_words),
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
        # ADC timing is 1 word = 4 samples; keep all following math in words.
        unit = CaptureParam.NUM_SAMPLES_IN_ADC_WORD
        # Normalize capture timing to an alternating [blank, duration, ...] chain.
        chain = _convert_cap_sampled_sequence_to_blanks_and_durations_chain(sequence)
        # Fold sequence.padding into the leading blank.
        chain[0] += sequence.padding
        # Build segment start offsets (starting at 0) for alignment.
        bounds = _segment_starts(chain)
        aligned: list[int] = (
            [
                0,
                # NOTE: Pre-blank is aligned to a 64-sample block boundary
                # (16 capture words) before capture starts.
                math.floor(bounds[1] / (CAPTURE_PRE_BLANK_ALIGNMENT_WORDS * unit))
                * CAPTURE_PRE_BLANK_ALIGNMENT_WORDS
                * unit,
                # Round all later boundaries down to ADC-word granularity.
            ]
            + [math.floor(bound / unit) * unit for bound in bounds[2:]]
        )
        # Convert aligned boundaries back to a word-based chain.
        new_chain = [int((up - low) / unit) for low, up in pairwise(aligned)] + [
            int(chain[-1])
        ]
        # Recalculate the final blank so total length matches the requested interval.
        total_duration_words = sum(new_chain)
        interval_words = int(interval_samples // unit)
        new_chain[-1] = interval_words - total_duration_words + new_chain[0]
        # Hardware requires at least one post-blank word after each duration.
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
        # Move the leading blank into capture_delay; the rest become sum sections.
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
        # Add integration while keeping already enabled DSP units.
        dsp = capprm.dsp_units_enabled
        dsp.append(DspUnit.INTEGRATION)
        # CaptureParam removes duplicates, so reapply the full list.
        capprm.sel_dsp_units_to_enable(*dsp)
        return capprm

    @classmethod
    def enable_sum(
        cls,
        capprm: CaptureParam,
    ) -> CaptureParam:
        """Enable sum DSP in the given capture parameter."""
        # Enable DSP summation of integrated values.
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
        # Demodulation requires both complex FIR and complex window coefficients.
        capprm.complex_fir_coefs = cls.fir_coefficient(f_GHz)
        capprm.complex_window_coefs = cls.window_coefficient(f_GHz)

        # Enable the DSP stages used for demodulation.
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
        # FIR taps are indexed over past samples ending at 0 ns.
        t_ns = SAMPLING_PERIOD * np.arange(-N_COEFS + 1, 1)  # [-30, -28, ..., 0]

        # rect window
        # window_function = MAX_VAL * np.ones(N_COEFS).astype(complex)

        # Use a Gaussian envelope to reduce edge effects and spectral leakage.
        mu = (t_ns[-1] + t_ns[0]) / 2
        sigma = (t_ns[-1] - t_ns[0]) / 6
        window_function = MAX_VAL * np.exp(-0.5 * (t_ns - mu) ** 2 / (sigma**2))

        # Modulate by e^(j2πft) to place the response at f_GHz.
        coefs = window_function * np.exp(1j * 2 * np.pi * f_GHz * t_ns)
        # Coefficients are consumed as integers in hardware, so return rounded values.
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
        # Window taps are spaced by the post-decimation period (8 ns).
        t_ns = N_DECIMATION * SAMPLING_PERIOD * np.arange(N_COEFS)  # [0, 8, ..., 16376]
        # Build a complex rotation window using e^(-j2πft) for basebanding.
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
        # Enable classification DSP and register both decision boundaries.
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

    Notes
    -----
    Example conversion:
    - `prev_blank = 2`
    - Subsequence wave lengths = `[3, 2, 4]`
    - Subsequence post blanks = `[5, None, 7]`
    - Top-level `post_blank = 1`
    - Resulting chain = `[2, 3, 5, 2, 0, 4, 8]`
      (`None` post blank is normalized to `0`, and the final blank is
      `7 + 1 = 8`)
    """
    # Start with the leading blank, then append [wave, blank] pairs.
    chain: list[int] = [sequence.prev_blank]
    for subseq in sequence.sub_sequences[:-1]:
        # NOTE: `None` is treated as no additional blank (0).
        # This makes "unset" and explicit zero equivalent here.
        # Each subsequence contributes its waveform length and trailing blank.
        chain.extend([subseq.real.shape[0], subseq.post_blank or 0])
    last_subseq = sequence.sub_sequences[-1]
    last_blank = (
        last_subseq.post_blank + sequence.post_blank
        if sequence.post_blank is not None and last_subseq.post_blank is not None
        # NOTE: Same permissive fallback as above.
        # Missing tail blank metadata is normalized to zero.
        else 0
    )
    # The last subsequence also includes top-level post_blank in its tail blank.
    chain.extend([last_subseq.real.shape[0], last_blank])
    return chain


def _convert_cap_sampled_sequence_to_blanks_and_durations_chain(
    sequence: CapSampledSequence,
) -> list[int]:
    """
    Convert a capture sequence into a `[blank, duration, blank, ...]` chain.

    The conversion merges nested blank contributors (slot/subsequence/top-level)
    into inter-subsequence blanks between capture durations.

    Parameters
    ----------
    sequence : CapSampledSequence
        Source capture sampled sequence.

    Returns
    -------
    list[int]
        Alternating blank/duration lengths in samples.

    Notes
    -----
    Example conversion:
    - `sequence.prev_blank = 10`
    - Subsequence 1:
      - `prev_blank = 6`
      - Slot 1: `duration = 8`, `post_blank = 2`
      - `post_blank = 4`
    - Subsequence 2:
      - `prev_blank = 12`
      - Slot 1: `duration = 10`, `post_blank = 3`
      - `post_blank = 5`
    - Top-level `sequence.post_blank = 7`
    - Inter-subsequence blank = `2 + 4 + 12 = 18`
    - Last blank = `3 + 5 + 7 = 15`
    - Resulting chain = `[16, 8, 18, 10, 15]`

    Raises
    ------
    ValueError
        Raised when any required blank value is missing.
    """
    seq = sequence
    subseqs = seq.sub_sequences
    non_final_subseqs = subseqs[:-1]
    following_subseqs = subseqs[1:]
    final_subseq = subseqs[-1]
    # Inter-subsequence blank = last slot post + previous subsequence post + next subsequence prev.
    # Example: 8 + 4 + 6 = 18
    #   prev_subseq.capture_slots[-1].post_blank = 8
    #   prev_subseq.post_blank = 4
    #   next_subseq.prev_blank = 6
    inter_subseq_blanks = [
        _require_int(
            prev_subseq.capture_slots[-1].post_blank
            + prev_subseq.post_blank
            + next_subseq.prev_blank
            if prev_subseq.capture_slots[-1].post_blank is not None
            and prev_subseq.post_blank is not None
            and next_subseq.prev_blank is not None
            else None,
            context="inter-subsequence blank",
        )
        for prev_subseq, next_subseq in zip(
            non_final_subseqs, following_subseqs, strict=True
        )
    ]
    last_blank = (
        # Tail blank = last slot post + last subsequence post + top-level post.
        _require_int(
            final_subseq.capture_slots[-1].post_blank
            + final_subseq.post_blank
            + seq.post_blank
            if final_subseq.capture_slots[-1].post_blank is not None
            and final_subseq.post_blank is not None
            else None,
            context="last blank",
        )
        # NOTE: Legacy behavior allows missing top-level tail blank by
        # normalizing to zero; later alignment/constraint logic repairs
        # the final shape.
        if seq.post_blank is not None
        else 0
    )
    # Leading blank combines sequence.prev_blank and the first subsequence prev_blank.
    # Example: sequence.prev_blank=10 and first subseq.prev_blank=6 -> 16.
    chain: list[int] = [seq.prev_blank + subseqs[0].prev_blank]
    for prev_subseq, inter_subseq_blank in zip(
        non_final_subseqs, inter_subseq_blanks, strict=True
    ):
        # For non-final subsequences, close with the corresponding inter-subsequence blank.
        _append_capture_slots(
            chain=chain,
            capture_slots=prev_subseq.capture_slots,
            last_blank=inter_subseq_blank,
        )
    # Final subsequence is closed with the computed last_blank.
    # Example tail blank: 12 + 5 + 7 = 24
    #   final slot post_blank=12, final subseq post_blank=5, sequence.post_blank=7.
    _append_capture_slots(
        chain=chain,
        capture_slots=final_subseq.capture_slots,
        last_blank=last_blank,
    )
    return chain


def _require_int(value: int | float | None, *, context: str) -> int:
    """Return integer value or raise when missing."""
    # In this module, None means a required value is missing, so fail fast.
    if value is None:
        raise ValueError(f"{context} must be set")
    return int(value)


def _segment_starts(lengths: list[int]) -> list[int]:
    """Return segment start positions where the first start is zero."""
    # [a,b,c] -> [0,a,a+b]; starts are needed only up to the last segment.
    return list(accumulate(lengths[:-1], initial=0))


def _append_capture_slots(
    *,
    chain: list[int],
    capture_slots: MutableSequence[CaptureSlots],
    last_blank: int,
) -> None:
    """Append one capture-subsequence slots into an alternating chain."""
    # For intermediate slots, use each slot's own post_blank.
    for slot in capture_slots[:-1]:
        chain.extend(
            [slot.duration, _require_int(slot.post_blank, context="slot blank")]
        )
    # For the final slot, use the caller-provided blank (inter-subsequence or tail).
    chain.extend([capture_slots[-1].duration, last_blank])
