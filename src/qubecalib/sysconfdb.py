"""Compatibility shim exposing system config APIs from qxdriver_quel."""

from __future__ import annotations

import importlib

_sysconfdb = importlib.import_module("qxdriver_quel.sysconfdb")


def __getattr__(name: str):
    return getattr(_sysconfdb, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_sysconfdb)))
