"""Pulse-sequence compatibility shim for qxdriver_quel."""

from __future__ import annotations

from qubecalib import neopulse as _neopulse


def __getattr__(name: str):
    return getattr(_neopulse, name)
