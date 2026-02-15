"""Sampled-sequence data models used by pulse and runtime converters."""

from __future__ import annotations

from collections.abc import MutableSequence
from dataclasses import asdict, dataclass, field

import numpy as np
from numpy.typing import NDArray

DEFAULT_SAMPLING_PERIOD: float = 2.0


@dataclass
class SampledSequenceBase:
    """Represent `SampledSequenceBase`."""

    target_name: str
    prev_blank: int = 0  # words
    sampling_period: float = DEFAULT_SAMPLING_PERIOD
    post_blank: int | None = None  # words
    repeats: int | None = None
    original_prev_blank: float | None = None  # ns
    original_post_blank: float | None = None  # ns
    padding: int = 0  # Sa
    modulation_frequency: float | None = None  # GHz

    def asdict(self) -> dict:
        """Execute asdict."""
        return asdict(self)


@dataclass
class GenSampledSubSequence:
    """Represent `GenSampledSubSequence`."""

    real: NDArray[np.float64]
    imag: NDArray[np.float64]
    repeats: int
    post_blank: int | None = None  # samples
    original_post_blank: float | None = None  # ns

    def asdict(self) -> dict:
        """Execute asdict."""
        return {
            "real": self.real.tolist(),
            "imag": self.imag.tolist(),
            "repeats": self.repeats,
            "post_blank": self.post_blank,
            "original_post_blank": self.original_post_blank,
        }


@dataclass
class GenSampledSequence(SampledSequenceBase):
    """Represent `GenSampledSequence`."""

    sub_sequences: MutableSequence[GenSampledSubSequence] = field(default_factory=list)
    readout_timings: MutableSequence[list[tuple[float, float]]] | None = None  # ns

    def asdict(self) -> dict:
        """Execute asdict."""
        return super().asdict() | {
            "sub_sequences": [_.asdict() for _ in self.sub_sequences],
            "readout_timings": None,
            "class": self.__class__.__name__,
        }


@dataclass
class CaptureSlots:
    """Represent `CaptureSlots`."""

    duration: int  # samples
    post_blank: int | None  # samples
    original_duration: float  # ns
    original_post_blank: float | None  # ns

    def asdict(self) -> dict:
        """Execute asdict."""
        return {}


@dataclass
class CapSampledSubSequence:
    """Represent `CapSampledSubSequence`."""

    capture_slots: MutableSequence[CaptureSlots]
    prev_blank: int  # samples
    post_blank: int | None  # samples
    original_prev_blank: float  # ns
    original_post_blank: float | None  # ns
    repeats: int | None

    def asdict(self) -> dict:
        """Execute asdict."""
        return asdict(self)


@dataclass
class CapSampledSequence(SampledSequenceBase):
    """Represent `CapSampledSequence`."""

    sub_sequences: MutableSequence[CapSampledSubSequence] = field(default_factory=list)
    readin_offsets: MutableSequence[list[tuple[float, float]]] | None = None  # ns

    def asdict(self) -> dict:
        """Execute asdict."""
        return super().asdict() | {
            "sub_sequences": [_.asdict() for _ in self.sub_sequences],
            "readin_offsets": None,
            "class": self.__class__.__name__,
        }
