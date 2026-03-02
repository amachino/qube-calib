"""Compatibility tests for qxdriver_quel1 namespace exports."""

from __future__ import annotations


def test_qxdriver_quel_top_level_exports_match_qubecalib() -> None:
    """Given qxdriver_quel1 package, when importing top-level symbols, then qxdriver_quel1 compatibility exports are available."""
    from qxdriver_quel1 import QubeCalib, Sequencer, pulse

    assert QubeCalib.__name__ == "QubeCalib"
    assert Sequencer.__name__ == "Sequencer"
    assert hasattr(pulse, "DEFAULT_SAMPLING_PERIOD")


def test_qxdriver_quel_qubecalib_module_exports_runtime_symbols() -> None:
    """Given qxdriver_quel1.qubecalib module, when importing runtime symbols, then required compatibility symbols are exposed."""
    from qxdriver_quel1.qubecalib import (
        BoxPool,
        CaptureParamTools,
        Converter,
        QubeCalib,
        Sequencer,
        WaveSequenceTools,
    )

    assert QubeCalib.__name__ == "QubeCalib"
    assert Sequencer.__name__ == "Sequencer"
    assert BoxPool.__name__ == "BoxPool"
    assert Converter.__name__ == "Converter"
    assert CaptureParamTools.__name__ == "CaptureParamTools"
    assert WaveSequenceTools.__name__ == "WaveSequenceTools"
