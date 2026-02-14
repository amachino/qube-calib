"""Compatibility shim for qubecalib direct single-action driver."""

from __future__ import annotations

from qxdriver_quel.instrument.quel.quel1.driver import single as _single


def __getattr__(name: str):
    return getattr(_single, name)
