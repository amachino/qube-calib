"""Compatibility shim exposing clock wrappers from qxdriver_quel."""

from __future__ import annotations

from qxdriver_quel.clockmaster_compat import (
    QuBEMasterClient,
    SequencerClient,
    register_box,
)

__all__ = [
    "QuBEMasterClient",
    "SequencerClient",
    "register_box",
]
