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
