"""Compatibility shim for qxdriver_quel QuEL1 skew helpers."""

from __future__ import annotations

from qubecalib.instrument.quel.quel1.tool import skew as _skew


def __getattr__(name: str):
    return getattr(_skew, name)
