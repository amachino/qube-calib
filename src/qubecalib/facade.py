"""Compatibility shim exposing facade APIs from qxdriver_quel."""

from __future__ import annotations

import importlib

_facade = importlib.import_module("qxdriver_quel.facade")


def __getattr__(name: str):
    return getattr(_facade, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_facade)))
