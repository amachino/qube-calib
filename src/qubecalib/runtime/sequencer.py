"""Compatibility shim exposing runtime sequencer APIs from qxdriver_quel."""

from __future__ import annotations

import importlib

_sequencer = importlib.import_module("qxdriver_quel.runtime.sequencer")


def __getattr__(name: str):
    return getattr(_sequencer, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_sequencer)))
