"""Typed capture results returned by direct-driver actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

import numpy as np
import numpy.typing as npt
from quel_ic_config import CapIqDataReader

from qxdriver_quel1.e7awg.compat import CaptureParam, DspUnit


@dataclass(frozen=True)
class WaveCaptureResult:
    """Wave capture payload from one capture unit."""

    sections: tuple[npt.NDArray[np.complex64], ...]
    kind: Literal["wave"] = "wave"


@dataclass(frozen=True)
class ClassificationCaptureResult:
    """DSP classification label payload from one capture unit."""

    labels: tuple[npt.NDArray[np.uint8], ...]
    kind: Literal["classification"] = "classification"


CaptureResult: TypeAlias = WaveCaptureResult | ClassificationCaptureResult


def read_capture_result(
    reader: CapIqDataReader,
    cprm: CaptureParam,
) -> CaptureResult:
    """Read a typed capture result from a reader according to capture DSP mode."""
    if DspUnit.CLASSIFICATION in cprm.dsp_units_enabled:
        return ClassificationCaptureResult(
            labels=tuple(
                np.asarray(section, dtype=np.uint8)
                for section in reader.as_class_list()
            )
        )
    return WaveCaptureResult(
        sections=(np.asarray(reader.rawwave(), dtype=np.complex64),)
    )
