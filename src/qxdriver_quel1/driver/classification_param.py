"""Classification parameter conversion for direct-driver capture settings."""

from __future__ import annotations

from typing import Any

import numpy as np

from qxdriver_quel1.classification import LineParam, normalize_line_param
from qxdriver_quel1.e7awg.compat import CaptureParam

try:
    from e7awghal.classification import ClassificationParam
except ModuleNotFoundError:  # pragma: no cover - depends on quelware install extras
    ClassificationParam = None  # type: ignore[assignment]


def classification_lines_from_capture_param(
    cprm: CaptureParam,
) -> tuple[LineParam, LineParam]:
    """Return both classification decision-function lines from a capture param."""
    try:
        line0 = normalize_line_param(cprm.classification_params[0])
        line1 = normalize_line_param(cprm.classification_params[1])
    except KeyError as exc:
        raise ValueError(
            "Classification DSP requires both decision functions 0 and 1."
        ) from exc
    return line0, line1


def _line_angle(line: LineParam) -> float:
    """Return the line angle expected by `ClassificationParam`."""
    a, b, _ = normalize_line_param(line)
    return float(np.degrees(np.arctan2(-a, b)))


def _point_on_line(line: LineParam) -> tuple[float, float]:
    """Return one point on the given line."""
    a, b, c = normalize_line_param(line)
    denom = a * a + b * b
    return (-a * c / denom, -b * c / denom)


def _intersection_point(
    line0: LineParam,
    line1: LineParam,
) -> tuple[float, float]:
    """Return the intersection point of two non-parallel lines."""
    a0, b0, c0 = normalize_line_param(line0)
    a1, b1, c1 = normalize_line_param(line1)
    det = a0 * b1 - a1 * b0
    if np.isclose(det, 0.0):
        raise ValueError("Classification lines are parallel and do not intersect.")
    x, y = np.linalg.solve(
        np.array([[a0, b0], [a1, b1]], dtype=np.float64),
        np.array([-c0, -c1], dtype=np.float64),
    )
    return (float(x), float(y))


def convert_classification_param(cprm: CaptureParam) -> Any:
    """Convert capture-param line equations into an e7awghal classification param."""
    if ClassificationParam is None:
        raise RuntimeError(
            "e7awghal.classification.ClassificationParam is required for "
            "direct-driver classification conversion."
        )
    line0, line1 = classification_lines_from_capture_param(cprm)

    a0, b0, _ = line0
    a1, b1, _ = line1
    det = a0 * b1 - a1 * b0
    if np.isclose(det, 0.0):
        pivot_x, pivot_y = _point_on_line(line0)
    else:
        pivot_x, pivot_y = _intersection_point(line0, line1)

    # e7awghal represents the sub line with the opposite normal direction.
    # Flip the equation before deriving the angle so the raw line registers
    # keep the same half-plane convention as the legacy e7awgsw parameters.
    sub_line_for_angle = (-line1[0], -line1[1], -line1[2])
    return ClassificationParam(
        pivot_x=pivot_x,
        pivot_y=pivot_y,
        angle_main=_line_angle(line0),
        angle_sub=_line_angle(sub_line_for_angle),
    )
