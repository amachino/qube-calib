"""Compatibility shim for qxdriver_quel common direct-driver types."""

from __future__ import annotations

from qubecalib.instrument.quel.quel1.driver import common as _common


def __getattr__(name: str):
    return getattr(_common, name)
