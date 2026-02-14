"""Import-path compatibility tests for qxdriver_quel."""

from __future__ import annotations


def test_qxdriver_quel_module_paths_for_backend_are_importable() -> None:
    """Given backend-facing module paths, when importing from qxdriver_quel, then symbols resolve."""
    from qxdriver_quel.clockmaster_compat import QuBEMasterClient, SequencerClient
    from qxdriver_quel.instrument.quel.quel1 import Quel1System
    from qxdriver_quel.instrument.quel.quel1.driver import (
        Action,
        AwgId,
        AwgSetting,
        NamedBox,
        RunitId,
        RunitSetting,
        TriggerSetting,
    )
    from qxdriver_quel.instrument.quel.quel1.tool import Skew

    assert QuBEMasterClient.__name__ == "QuBEMasterClient"
    assert SequencerClient.__name__ == "SequencerClient"
    assert Quel1System.__name__ == "Quel1System"
    assert Action.__name__ == "Action"
    assert AwgId.__name__ == "AwgId"
    assert AwgSetting.__name__ == "AwgSetting"
    assert NamedBox.__name__ == "NamedBox"
    assert RunitId.__name__ == "RunitId"
    assert RunitSetting.__name__ == "RunitSetting"
    assert TriggerSetting.__name__ == "TriggerSetting"
    assert Skew.__name__ == "Skew"


def test_qxdriver_quel_driver_submodules_are_importable() -> None:
    """Given direct-driver submodule imports, when importing multi/single modules, then Action is available from each."""
    from qxdriver_quel.instrument.quel.quel1.driver import multi, single

    assert hasattr(single, "Action")
    assert hasattr(multi, "Action")


def test_qxdriver_quel_e7compat_exports_are_importable() -> None:
    """Given legacy e7 compatibility types, when importing from qxdriver_quel, then required symbols resolve."""
    from qxdriver_quel.e7compat import CaptureParam, DspUnit, WaveSequence

    assert CaptureParam.__name__ == "CaptureParam"
    assert WaveSequence.__name__ == "WaveSequence"
    assert DspUnit.__name__ == "DspUnit"


def test_qxdriver_quel_runtime_and_config_modules_are_importable() -> None:
    """Given runtime/config module paths, when importing from qxdriver_quel, then compatibility symbols resolve."""
    from qxdriver_quel import __version__
    from qxdriver_quel.facade import QubeCalib
    from qxdriver_quel.qubecalib import Executor
    from qxdriver_quel.runtime import BoxPool, Sequencer
    from qxdriver_quel.sysconfdb import SystemConfigDatabase

    assert isinstance(__version__, str)
    assert QubeCalib.__name__ == "QubeCalib"
    assert Executor.__name__ == "Executor"
    assert BoxPool.__name__ == "BoxPool"
    assert Sequencer.__name__ == "Sequencer"
    assert SystemConfigDatabase.__name__ == "SystemConfigDatabase"


def test_qxdriver_quel_compat_layer_exports_are_importable() -> None:
    """Given unified compat layer imports, when importing from qxdriver_quel.compat, then symbols resolve."""
    from qxdriver_quel.compat import (
        Action,
        BoxPool,
        CapSampledSubSequence,
        CaptureSlots,
        GenSampledSubSequence,
        QubeCalib,
        QuBEMasterClient,
        Quel1Box,
        Quel1ConfigOption,
        Sequencer,
        SequencerClient,
        Skew,
    )

    assert QubeCalib.__name__ == "QubeCalib"
    assert Sequencer.__name__ == "Sequencer"
    assert QuBEMasterClient.__name__ == "QuBEMasterClient"
    assert SequencerClient.__name__ == "SequencerClient"
    assert Action.__name__ == "Action"
    assert GenSampledSubSequence.__name__ == "GenSampledSubSequence"
    assert CapSampledSubSequence.__name__ == "CapSampledSubSequence"
    assert CaptureSlots.__name__ == "CaptureSlots"
    assert Skew.__name__ == "Skew"
    assert BoxPool.__name__ == "BoxPool"
    assert Quel1Box.__name__ == "Quel1Box"
    assert Quel1ConfigOption.__name__ == "Quel1ConfigOption"
