"""Compatibility shim exposing pulse-sequence helpers from qxdriver_quel."""

from __future__ import annotations

import importlib

_neopulse = importlib.import_module("qxdriver_quel.neopulse")


def __getattr__(name: str):
    return getattr(_neopulse, name)
