"""Compatibility shim exposing resource-map helpers from qxdriver_quel."""

from __future__ import annotations

import importlib

_resource_map = importlib.import_module("qxdriver_quel.resource_map")


def __getattr__(name: str):
    return getattr(_resource_map, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_resource_map)))
