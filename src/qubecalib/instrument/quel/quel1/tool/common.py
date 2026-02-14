"""Compatibility shim exposing QuEL1 tool common helpers from qxdriver_quel."""

from __future__ import annotations

import importlib

_common = importlib.import_module("qxdriver_quel.instrument.quel.quel1.tool.common")


def __getattr__(name: str):
    return getattr(_common, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_common)))
