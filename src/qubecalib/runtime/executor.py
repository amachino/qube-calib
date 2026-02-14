"""Compatibility shim exposing runtime executor APIs from qxdriver_quel."""

from __future__ import annotations

import importlib

_executor = importlib.import_module("qxdriver_quel.runtime.executor")


def __getattr__(name: str):
    return getattr(_executor, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_executor)))
