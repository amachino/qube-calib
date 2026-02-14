"""Tests for e7 conversion utilities."""

from __future__ import annotations

import numpy as np
import pytest
from qubecalib.e7utils import (
    CaptureParamTools,
    WaveSequenceTools,
    _convert_cap_sampled_sequence_to_blanks_and_durations_chain,
    _convert_gen_sampled_sequence_to_blanks_and_waves_chain,
)
from qubecalib.neopulse import (
    CapSampledSequence,
    CapSampledSubSequence,
    CaptureSlots,
    GenSampledSequence,
    GenSampledSubSequence,
)


def test_create_allows_none_toplevel_post_blank() -> None:
    """Given None top-level post blank, when creating CaptureParam, then conversion succeeds."""
    sequence = CapSampledSequence(
        target_name="RQ00",
        prev_blank=0,
        post_blank=None,
        repeats=1,
        sub_sequences=[
            CapSampledSubSequence(
                capture_slots=[
                    CaptureSlots(
                        duration=16,
                        post_blank=0,
                        original_duration=32.0,
                        original_post_blank=0.0,
                    )
                ],
                prev_blank=8,
                post_blank=0,
                original_prev_blank=16.0,
                original_post_blank=0.0,
                repeats=1,
            )
        ],
    )

    capprm = CaptureParamTools.create(
        sequence=sequence,
        capture_delay_words=0,
        repeats=1,
        interval_samples=256,
    )

    assert capprm.capture_delay >= 0
    assert len(capprm.sum_section_list) == 1


def test_wave_create_accepts_single_subsequence() -> None:
    """Given one gen subsequence, when creating WaveSequence, then conversion succeeds."""
    sequence = GenSampledSequence(
        target_name="RQ00",
        prev_blank=8,
        post_blank=None,
        repeats=1,
        sub_sequences=[
            GenSampledSubSequence(
                real=np.array([0.1, 0.2, 0.3, 0.4]),
                imag=np.array([0.0, 0.0, 0.0, 0.0]),
                repeats=1,
                post_blank=0,
            )
        ],
    )

    wseq = WaveSequenceTools.create(
        sequence=sequence,
        wait_words=0,
        repeats=1,
        interval_samples=256,
    )

    assert wseq.num_chunks == 1


def test_convert_gen_chain_handles_none_blanks() -> None:
    """Given optional blanks are None, when converting gen chain, then they are normalized."""
    sequence = GenSampledSequence(
        target_name="RQ00",
        prev_blank=4,
        post_blank=5,
        sub_sequences=[
            GenSampledSubSequence(
                real=np.array([0.0, 0.1, 0.2]),
                imag=np.array([0.0, 0.0, 0.0]),
                repeats=1,
                post_blank=None,
            ),
            GenSampledSubSequence(
                real=np.array([0.3, 0.4]),
                imag=np.array([0.0, 0.0]),
                repeats=1,
                post_blank=7,
            ),
        ],
    )

    chain = _convert_gen_sampled_sequence_to_blanks_and_waves_chain(sequence)

    assert chain == [4, 3, 0, 2, 12]


def test_convert_gen_chain_matches_documented_example() -> None:
    """Given the documented gen-chain example, when converting, then the expected chain is produced."""
    sequence = GenSampledSequence(
        target_name="RQ00",
        prev_blank=2,
        post_blank=1,
        sub_sequences=[
            GenSampledSubSequence(
                real=np.array([0.1, 0.2, 0.3]),
                imag=np.array([0.0, 0.0, 0.0]),
                repeats=1,
                post_blank=5,
            ),
            GenSampledSubSequence(
                real=np.array([0.4, 0.5]),
                imag=np.array([0.0, 0.0]),
                repeats=1,
                post_blank=None,
            ),
            GenSampledSubSequence(
                real=np.array([0.6, 0.7, 0.8, 0.9]),
                imag=np.array([0.0, 0.0, 0.0, 0.0]),
                repeats=1,
                post_blank=7,
            ),
        ],
    )

    chain = _convert_gen_sampled_sequence_to_blanks_and_waves_chain(sequence)

    assert chain == [2, 3, 5, 2, 0, 4, 8]


def test_convert_cap_chain_merges_blank_bridge_and_last_blank() -> None:
    """Given nested capture blanks, when converting cap chain, then bridge and tail are merged."""
    sequence = CapSampledSequence(
        target_name="RQ00",
        prev_blank=4,
        post_blank=13,
        repeats=1,
        sub_sequences=[
            CapSampledSubSequence(
                capture_slots=[
                    CaptureSlots(
                        duration=8,
                        post_blank=2,
                        original_duration=8.0,
                        original_post_blank=2.0,
                    )
                ],
                prev_blank=6,
                post_blank=3,
                original_prev_blank=6.0,
                original_post_blank=3.0,
                repeats=1,
            ),
            CapSampledSubSequence(
                capture_slots=[
                    CaptureSlots(
                        duration=10,
                        post_blank=11,
                        original_duration=10.0,
                        original_post_blank=11.0,
                    )
                ],
                prev_blank=5,
                post_blank=7,
                original_prev_blank=5.0,
                original_post_blank=7.0,
                repeats=1,
            ),
        ],
    )

    chain = _convert_cap_sampled_sequence_to_blanks_and_durations_chain(sequence)

    assert chain == [10, 8, 10, 10, 31]


def test_convert_cap_chain_matches_documented_example() -> None:
    """Given the documented cap-chain example, when converting, then the expected chain is produced."""
    sequence = CapSampledSequence(
        target_name="RQ00",
        prev_blank=10,
        post_blank=7,
        repeats=1,
        sub_sequences=[
            CapSampledSubSequence(
                capture_slots=[
                    CaptureSlots(
                        duration=8,
                        post_blank=2,
                        original_duration=8.0,
                        original_post_blank=2.0,
                    )
                ],
                prev_blank=6,
                post_blank=4,
                original_prev_blank=6.0,
                original_post_blank=4.0,
                repeats=1,
            ),
            CapSampledSubSequence(
                capture_slots=[
                    CaptureSlots(
                        duration=10,
                        post_blank=3,
                        original_duration=10.0,
                        original_post_blank=3.0,
                    )
                ],
                prev_blank=12,
                post_blank=5,
                original_prev_blank=12.0,
                original_post_blank=5.0,
                repeats=1,
            ),
        ],
    )

    chain = _convert_cap_sampled_sequence_to_blanks_and_durations_chain(sequence)

    assert chain == [16, 8, 18, 10, 15]


def test_wave_create_rejects_out_of_range_iq() -> None:
    """Given iq magnitude greater than one, when creating wave sequence, then ValueError is raised."""
    sequence = GenSampledSequence(
        target_name="RQ00",
        prev_blank=0,
        post_blank=0,
        repeats=1,
        sub_sequences=[
            GenSampledSubSequence(
                real=np.array([1.1, 0.0]),
                imag=np.array([0.0, 0.0]),
                repeats=1,
                post_blank=0,
            )
        ],
    )

    with pytest.raises(ValueError, match="magnitude of iq signal must not exceed 1"):
        WaveSequenceTools.create(
            sequence=sequence,
            wait_words=0,
            repeats=1,
            interval_samples=64,
        )


def test_wave_create_places_subsequences_at_expected_offsets() -> None:
    """Given multiple subsequences and blanks, when creating wave sequence, then iq samples are written at expected offsets."""
    sequence = GenSampledSequence(
        target_name="RQ00",
        prev_blank=2,
        post_blank=4,
        repeats=1,
        sub_sequences=[
            GenSampledSubSequence(
                real=np.array([0.5, -0.5]),
                imag=np.array([0.0, 0.25]),
                repeats=1,
                post_blank=3,
            ),
            GenSampledSubSequence(
                real=np.array([0.25, -0.25]),
                imag=np.array([0.5, -0.5]),
                repeats=1,
                post_blank=1,
            ),
        ],
    )

    wseq = WaveSequenceTools.create(
        sequence=sequence,
        wait_words=0,
        repeats=1,
        interval_samples=256,
    )

    samples = wseq.chunk(0).wave_data.samples
    expected_head = np.array(
        [
            [0, 0],  # leading blank
            [0, 0],  # leading blank
            [16383, 0],  # subseq-1 sample-0
            [-16383, 8191],  # subseq-1 sample-1
            [0, 0],  # inter-subseq blank
            [0, 0],  # inter-subseq blank
            [0, 0],  # inter-subseq blank
            [8191, 16383],  # subseq-2 sample-0
            [-8191, -16383],  # subseq-2 sample-1
        ],
        dtype=np.float32,
    )

    np.testing.assert_array_equal(samples[:9], expected_head)
