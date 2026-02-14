"""Compatibility shim exposing runtime converter APIs from qxdriver_quel."""

from __future__ import annotations

import importlib

_converter = importlib.import_module("qxdriver_quel.runtime.converter")


def __getattr__(name: str):
    return getattr(_converter, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_converter)))
