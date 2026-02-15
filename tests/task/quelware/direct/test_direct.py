# ruff: noqa

from __future__ import annotations

import quel_ic_config


def test_quel_ic_config_version() -> None:
    """Given migration target, quel_ic_config major.minor is 0.10."""
    assert quel_ic_config.__version__.startswith("0.10.")
