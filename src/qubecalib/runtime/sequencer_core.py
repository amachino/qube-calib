"""Compatibility shim exposing runtime core-sequencer APIs from qxdriver_quel."""

from __future__ import annotations

import importlib

_sequencer_core = importlib.import_module("qxdriver_quel.runtime.sequencer_core")


def __getattr__(name: str):
    return getattr(_sequencer_core, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_sequencer_core)))
