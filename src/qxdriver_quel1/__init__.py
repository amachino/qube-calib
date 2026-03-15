# ruff: noqa

"""QuEL driver package with qubecalib-compatible top-level exports."""

from __future__ import annotations

import importlib
import importlib.metadata
from typing import TYPE_CHECKING

try:
    __version__ = importlib.metadata.version("qxdriver-quel1")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

if TYPE_CHECKING:
    import qxdriver_quel1.pulse as pulse

    from qxdriver_quel1.qubecalib import QubeCalib, Sequencer

__all__ = [
    "QubeCalib",
    "Sequencer",
    "__version__",
    "pulse",
]


def __getattr__(name: str):
    if name in {"QubeCalib", "Sequencer"}:
        from qxdriver_quel1.qubecalib import QubeCalib, Sequencer

        return {"QubeCalib": QubeCalib, "Sequencer": Sequencer}[name]
    if name == "pulse":
        return importlib.import_module("qxdriver_quel1.pulse")
    raise AttributeError(name)
