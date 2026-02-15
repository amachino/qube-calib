"""Compatibility tests for legacy e7-style APIs."""

from __future__ import annotations

import pytest
from qxdriver_quel.e7awg.compat import WaveSequence


def test_add_chunk_accepts_positional_iq_samples() -> None:
    """Given IQ samples, when add_chunk uses positional form, then one chunk is stored."""
    sequence = WaveSequence(num_wait_words=0, num_repeats=1)

    sequence.add_chunk([(1, 0)] * 64, num_blank_words=2, num_repeats=3)

    assert sequence.num_chunks == 1
    assert sequence.chunk(0).num_blank_words == 2
    assert sequence.chunk(0).num_repeats == 3


def test_add_chunk_rejects_invalid_shape() -> None:
    """Given malformed IQ samples, when add_chunk is called, then ValueError is raised."""
    sequence = WaveSequence()

    with pytest.raises(
        ValueError,
        match="iq_samples must be complex array or Nx2 real array",
    ):
        sequence.add_chunk([[1, 2, 3]])
