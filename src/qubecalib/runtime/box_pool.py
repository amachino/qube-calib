"""Compatibility shim exposing runtime box-pool APIs from qxdriver_quel."""

from __future__ import annotations

import importlib

_box_pool = importlib.import_module("qxdriver_quel.runtime.box_pool")


def __getattr__(name: str):
    return getattr(_box_pool, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_box_pool)))
