"""Compatibility shim for qubecalib direct-driver compat helpers."""

from __future__ import annotations

from qxdriver_quel.instrument.quel.quel1.driver import compat as _compat


def __getattr__(name: str):
    return getattr(_compat, name)
