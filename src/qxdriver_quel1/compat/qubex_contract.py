"""Static export-name checks for qxdriver compat contract with qubex."""

from __future__ import annotations

import importlib
from typing import Final

from qxdriver_quel1.compat import exports

REQUIRED_EXPORT_NAMES: Final[tuple[str, ...]] = (
    "DEFAULT_SAMPLING_PERIOD",
    "Action",
    "AwgId",
    "AwgSetting",
    "BoxPool",
    "CapSampledSequence",
    "CapSampledSubSequence",
    "CaptureParamTools",
    "CaptureSlots",
    "Converter",
    "GenSampledSequence",
    "GenSampledSubSequence",
    "MultiAction",
    "NamedBox",
    "QuBEMasterClient",
    "QubeCalib",
    "Quel1Box",
    "Quel1ConfigOption",
    "Quel1System",
    "RunitId",
    "RunitSetting",
    "Sequencer",
    "SequencerClient",
    "SingleAction",
    "SingleAwgId",
    "SingleAwgSetting",
    "SingleRunitId",
    "SingleRunitSetting",
    "SingleTriggerSetting",
    "Skew",
    "TriggerSetting",
    "WaveSequenceTools",
)


missing = [name for name in REQUIRED_EXPORT_NAMES if name not in exports.EXPORTS]
if missing:
    missing_str = ", ".join(missing)
    raise RuntimeError(f"Missing compat exports: {missing_str}")


def _validate_module_alignment() -> None:
    """Validate that compat exports align with direct/single/multi runtime modules."""
    direct_module = importlib.import_module(exports.Action.__module__)
    single_module = importlib.import_module(exports.SingleAction.__module__)
    multi_module = importlib.import_module(exports.MultiAction.__module__)

    direct_expected = {
        "AwgId": exports.AwgId,
        "AwgSetting": exports.AwgSetting,
        "RunitId": exports.RunitId,
        "RunitSetting": exports.RunitSetting,
        "TriggerSetting": exports.TriggerSetting,
    }
    single_expected = {
        "AwgId": exports.SingleAwgId,
        "AwgSetting": exports.SingleAwgSetting,
        "RunitId": exports.SingleRunitId,
        "RunitSetting": exports.SingleRunitSetting,
        "TriggerSetting": exports.SingleTriggerSetting,
    }

    mismatched: list[str] = []
    for name, symbol in direct_expected.items():
        if getattr(direct_module, name, None) is not symbol:
            mismatched.append(f"direct.{name}")
    for name, symbol in single_expected.items():
        if getattr(single_module, name, None) is not symbol:
            mismatched.append(f"single.{name}")
    if getattr(multi_module, "Action", None) is not exports.MultiAction:
        mismatched.append("multi.Action")

    if mismatched:
        mismatched_str = ", ".join(mismatched)
        raise RuntimeError(f"Mismatched compat export bindings: {mismatched_str}")


def _validate_class_distinctness() -> None:
    """Validate that direct and single setting classes remain distinct objects."""
    pairs = (
        ("AwgId", exports.AwgId, exports.SingleAwgId),
        ("AwgSetting", exports.AwgSetting, exports.SingleAwgSetting),
        ("RunitId", exports.RunitId, exports.SingleRunitId),
        ("RunitSetting", exports.RunitSetting, exports.SingleRunitSetting),
        ("TriggerSetting", exports.TriggerSetting, exports.SingleTriggerSetting),
    )
    duplicated = [name for name, direct, single in pairs if direct is single]
    if duplicated:
        duplicated_str = ", ".join(duplicated)
        raise RuntimeError(
            f"Direct/Single compatibility classes must be distinct: {duplicated_str}"
        )


_validate_module_alignment()
_validate_class_distinctness()
