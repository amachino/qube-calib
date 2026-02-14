"""Compatibility shim for qxdriver_quel QuEL1 tool common helpers."""

from __future__ import annotations

from qubecalib.instrument.quel.quel1.tool import common as _common


def __getattr__(name: str):
    return getattr(_common, name)
