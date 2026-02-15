# ruff: noqa

"""QuEL driver package with qubecalib-compatible top-level exports."""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

__version__ = "3.1.16beta3"

if TYPE_CHECKING:
    import qxdriver_quel.pulse as pulse

    from qxdriver_quel.qubecalib import QubeCalib, Sequencer

__all__ = [
    "QubeCalib",
    "Sequencer",
    "__version__",
    "pulse",
]


def __getattr__(name: str):
    if name in {"QubeCalib", "Sequencer"}:
        from qxdriver_quel.qubecalib import QubeCalib, Sequencer

        return {"QubeCalib": QubeCalib, "Sequencer": Sequencer}[name]
    if name == "pulse":
        return importlib.import_module("qxdriver_quel.pulse")
    raise AttributeError(name)
