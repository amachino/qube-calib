"""QuEL driver package with qubecalib-compatible top-level exports."""

from __future__ import annotations

from typing import TYPE_CHECKING

from qubecalib import neopulse

if TYPE_CHECKING:
    from qubecalib.qubecalib import QubeCalib, Sequencer

__all__ = [
    "QubeCalib",
    "Sequencer",
    "neopulse",
]


def __getattr__(name: str):
    if name in {"QubeCalib", "Sequencer"}:
        from qubecalib.qubecalib import QubeCalib, Sequencer

        return {"QubeCalib": QubeCalib, "Sequencer": Sequencer}[name]
    raise AttributeError(name)
