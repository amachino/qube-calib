"""Compatibility shim for qxdriver_quel direct-driver compat helpers."""

from __future__ import annotations

from qubecalib.instrument.quel.quel1.driver import compat as _compat


def __getattr__(name: str):
    return getattr(_compat, name)
