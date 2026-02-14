"""Compatibility shim for qubecalib direct multi-action driver."""

from __future__ import annotations

from qxdriver_quel.instrument.quel.quel1.driver import multi as _multi


def __getattr__(name: str):
    return getattr(_multi, name)
