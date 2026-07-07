"""Public DSP classification line types."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass

LineParam = tuple[float, float, float]


@dataclass(frozen=True)
class ClassificationLineSet:
    """Two DSP classification lines for one capture target."""

    line0: LineParam
    line1: LineParam


ClassificationLineMap = Mapping[str, ClassificationLineSet]


def normalize_line_param(line: LineParam) -> LineParam:
    """Return a validated line parameter tuple."""
    if len(line) != 3:
        raise ValueError("Classification line parameters must have exactly 3 values.")
    a, b, c = (float(value) for value in line)
    if not all(math.isfinite(value) for value in (a, b, c)):
        raise ValueError("Classification line parameters must be finite.")
    if math.isclose(a, 0.0) and math.isclose(b, 0.0):
        raise ValueError("Classification line coefficients must not both be zero.")
    return (a, b, c)


def normalize_classification_line_set(
    line_set: ClassificationLineSet,
) -> ClassificationLineSet:
    """Return a validated classification line set."""
    return ClassificationLineSet(
        line0=normalize_line_param(line_set.line0),
        line1=normalize_line_param(line_set.line1),
    )
