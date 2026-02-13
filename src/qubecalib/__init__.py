"""Calibration package for QuBE."""

from typing import TYPE_CHECKING

__version__ = "3.1.16beta3"

from . import neopulse

if TYPE_CHECKING:
    from .qubecalib import QubeCalib, Sequencer

__all__ = [
    "QubeCalib",
    "Sequencer",
    "neopulse",
]


def __getattr__(name: str):
    if name in {"QubeCalib", "Sequencer"}:
        from .qubecalib import QubeCalib, Sequencer

        return {"QubeCalib": QubeCalib, "Sequencer": Sequencer}[name]
    raise AttributeError(name)
