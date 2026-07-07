"""Scoped e7awghal patch for raw DSP classification line registers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock
from typing import Any

import numpy as np
import numpy.typing as npt

from qxdriver_quel1.classification import LineParam, normalize_line_param

RAW_CLASSIFICATION_LINES_ATTR = "__qxdriver_raw_classification_lines__"

_PATCH_LOCK = RLock()


def _line_to_reg_half(
    line: LineParam,
    total_exponent_offset: int,
) -> npt.NDArray[np.float32]:
    """Convert one raw line equation into the register half used by e7awghal."""
    a, b, c = normalize_line_param(line)
    coeff_max = max(abs(a), abs(b))
    scale = 32767.0 / coeff_max
    return np.asarray(
        [
            a * scale,
            b * scale,
            c * scale * float(1 << total_exponent_offset),
        ],
        dtype=np.float32,
    )


def _classification_reg_file_class() -> type:
    try:
        from e7awghal import capunit
    except ImportError as exc:  # pragma: no cover - depends on quelware extras
        raise RuntimeError(
            "e7awghal is required for raw DSP classification line conversion."
        ) from exc

    classification_reg_file_cls = getattr(
        capunit,
        "_CapParamClassificationRegFile",
        None,
    )
    if classification_reg_file_cls is None:
        raise RuntimeError(
            "e7awghal.capunit._CapParamClassificationRegFile is required for "
            "raw DSP classification line conversion."
        )
    return classification_reg_file_cls


@contextmanager
def patched_classification_register_builder(
    *,
    required: bool,
) -> Iterator[None]:
    """
    Temporarily patch e7awghal classification register generation.

    e7awghal normally derives classification registers from pivot/angle values.
    That conversion cannot preserve parallel separated decision lines, so the
    direct driver stores raw line equations on `CapParam` and this scoped patch
    writes those equations to the private register file while `config_runit`
    builds hardware registers.
    """
    if not required:
        yield
        return

    with _PATCH_LOCK:
        classification_reg_file_cls = _classification_reg_file_class()
        original_fromcapparam = classification_reg_file_cls.fromcapparam

        def _classification_fromcapparam(cls: type, cp: Any) -> Any:
            lines = getattr(cp, RAW_CLASSIFICATION_LINES_ATTR, None)
            if lines is None:
                return original_fromcapparam(cp)
            line0, line1 = lines
            reg_file = cls()
            total_exponent_offset = cp.total_exponent_offset()
            reg_file.p0 = _line_to_reg_half(line0, total_exponent_offset)
            reg_file.p1 = _line_to_reg_half(line1, total_exponent_offset)
            return reg_file

        classification_reg_file_cls.fromcapparam = classmethod(
            _classification_fromcapparam
        )
        try:
            yield
        finally:
            classification_reg_file_cls.fromcapparam = original_fromcapparam
