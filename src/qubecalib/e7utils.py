"""Compatibility shim exposing e7 utility helpers from qxdriver_quel."""

from __future__ import annotations

import importlib

_e7utils = importlib.import_module("qxdriver_quel.e7utils")


def __getattr__(name: str):
    return getattr(_e7utils, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_e7utils)))
