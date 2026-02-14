"""QuEL driver package with qubecalib-compatible top-level exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qxdriver_quel.qubecalib import QubeCalib, Sequencer

__all__ = [
    "QubeCalib",
    "Sequencer",
    "neopulse",
]


def __getattr__(name: str):
    if name in {"QubeCalib", "Sequencer"}:
        from qxdriver_quel.qubecalib import QubeCalib, Sequencer

        return {"QubeCalib": QubeCalib, "Sequencer": Sequencer}[name]
    if name == "neopulse":
        return importlib.import_module("qxdriver_quel.neopulse")
    raise AttributeError(name)
