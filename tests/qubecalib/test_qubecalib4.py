# ruff: noqa

import os
from typing import Generator

import pytest
from qxdriver_quel.qubecalib import QubeCalib


@pytest.fixture(name="qc4")
def qxdriver_quel() -> Generator[QubeCalib, None, None]:
    """Return a QubeCalib object with a sample config file."""
    cwd = os.getcwd()
    os.chdir(os.path.dirname(__file__))
    yield QubeCalib("sample_config.json")
    os.chdir(cwd)


# def test_sequencer_execute() -> None:
