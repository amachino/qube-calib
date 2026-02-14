"""Tests for e7 conversion utilities."""

from __future__ import annotations

import numpy as np
from qubecalib.e7utils import CaptureParamTools, WaveSequenceTools
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
