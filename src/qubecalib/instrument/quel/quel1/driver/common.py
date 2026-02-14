"""Compatibility shim for qubecalib common direct-driver types."""

from __future__ import annotations

from qxdriver_quel.instrument.quel.quel1.driver import common as _common


def __getattr__(name: str):
    return getattr(_common, name)
