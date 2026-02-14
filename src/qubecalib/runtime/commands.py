"""Compatibility shim exposing runtime command APIs from qxdriver_quel."""

from __future__ import annotations

import importlib

_commands = importlib.import_module("qxdriver_quel.runtime.commands")


def __getattr__(name: str):
    return getattr(_commands, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_commands)))
