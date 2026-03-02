"""Import-path compatibility tests for qxdriver_quel1."""

from __future__ import annotations

import importlib
import sys


def test_qxdriver_quel_module_paths_for_backend_are_importable() -> None:
    """Given backend-facing module paths, when importing from qxdriver_quel1, then symbols resolve."""
    from qxdriver_quel1.clockmaster.compat import QuBEMasterClient, SequencerClient
    from qxdriver_quel1.driver import (
        Action,
        AwgId,
        AwgSetting,
        NamedBox,
        Quel1System,
        RunitId,
        RunitSetting,
        TriggerSetting,
    )
    from qxdriver_quel1.tool import Skew

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
    from qxdriver_quel1.driver import multi, single

    assert hasattr(single, "Action")
    assert hasattr(multi, "Action")


def test_qxdriver_quel_e7compat_exports_are_importable() -> None:
    """Given legacy e7 compatibility types, when importing from qxdriver_quel1, then required symbols resolve."""
    from qxdriver_quel1.e7awg.compat import CaptureParam, DspUnit, WaveSequence

    assert CaptureParam.__name__ == "CaptureParam"
    assert WaveSequence.__name__ == "WaveSequence"
    assert DspUnit.__name__ == "DspUnit"


def test_qxdriver_quel_runtime_and_config_modules_are_importable() -> None:
    """Given runtime/config module paths, when importing from qxdriver_quel1, then compatibility symbols resolve."""
    from qxdriver_quel1 import __version__
    from qxdriver_quel1.qubecalib import Executor, QubeCalib
    from qxdriver_quel1.runtime import BoxPool, Sequencer
    from qxdriver_quel1.sysconf import SystemConfigDatabase

    assert isinstance(__version__, str)
    assert QubeCalib.__name__ == "QubeCalib"
    assert Executor.__name__ == "Executor"
    assert BoxPool.__name__ == "BoxPool"
    assert Sequencer.__name__ == "Sequencer"
    assert SystemConfigDatabase.__name__ == "SystemConfigDatabase"


def test_qxdriver_quel_compat_layer_exports_are_importable() -> None:
    """Given unified compat layer imports, when importing from qxdriver_quel1.compat, then symbols resolve."""
    from qxdriver_quel1.compat import (
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
        SingleAwgSetting,
        SingleRunitSetting,
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
    assert SingleAwgSetting.__name__ == "AwgSetting"
    assert SingleRunitSetting.__name__ == "RunitSetting"
    assert Skew.__name__ == "Skew"
    assert BoxPool.__name__ == "BoxPool"
    assert Quel1Box.__name__ == "Quel1Box"
    assert Quel1ConfigOption.__name__ == "Quel1ConfigOption"


def test_qxdriver_quel_compat_import_executes_qubex_contract_validation() -> None:
    """Given compat import, contract validation module is loaded as part of the public entrypoint."""
    sys.modules.pop("qxdriver_quel1.compat.qubex_contract", None)
    sys.modules.pop("qxdriver_quel1.compat", None)

    importlib.import_module("qxdriver_quel1.compat")

    assert "qxdriver_quel1.compat.qubex_contract" in sys.modules


def test_qxdriver_quel_single_setting_exports_align_with_single_action_module() -> None:
    """Given compat exports, Single* classes match SingleAction module and remain distinct from common classes."""
    from qxdriver_quel1.compat import (
        Action,
        AwgId,
        AwgSetting,
        MultiAction,
        RunitId,
        RunitSetting,
        SingleAction,
        SingleAwgId,
        SingleAwgSetting,
        SingleRunitId,
        SingleRunitSetting,
        SingleTriggerSetting,
        TriggerSetting,
    )

    single_module = importlib.import_module(SingleAction.__module__)
    direct_module = importlib.import_module(Action.__module__)
    multi_module = importlib.import_module(MultiAction.__module__)

    assert SingleAwgId is single_module.AwgId
    assert SingleAwgSetting is single_module.AwgSetting
    assert SingleRunitId is single_module.RunitId
    assert SingleRunitSetting is single_module.RunitSetting
    assert SingleTriggerSetting is single_module.TriggerSetting

    assert AwgId is direct_module.AwgId
    assert AwgSetting is direct_module.AwgSetting
    assert RunitId is direct_module.RunitId
    assert RunitSetting is direct_module.RunitSetting
    assert TriggerSetting is direct_module.TriggerSetting

    assert Action is not SingleAction
    assert Action is not MultiAction
    assert SingleAction is not MultiAction
    assert AwgId is not SingleAwgId
    assert AwgSetting is not SingleAwgSetting
    assert RunitId is not SingleRunitId
    assert RunitSetting is not SingleRunitSetting
    assert TriggerSetting is not SingleTriggerSetting

    assert Action.__module__.endswith(".driver.common")
    assert SingleAction.__module__.endswith(".driver.single")
    assert multi_module.Action is MultiAction
