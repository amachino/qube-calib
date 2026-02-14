"""Compatibility shim exposing QuEL1 skew helpers from qxdriver_quel."""

from __future__ import annotations

import importlib

_skew = importlib.import_module("qxdriver_quel.instrument.quel.quel1.tool.skew")


def __getattr__(name: str):
    return getattr(_skew, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_skew)))
