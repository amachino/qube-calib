"""Static export-name checks for qxdriver compat contract with qubex."""

from __future__ import annotations

from typing import Final

from qxdriver_quel.compat import exports

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
    "Skew",
    "TriggerSetting",
    "WaveSequenceTools",
)


missing = [name for name in REQUIRED_EXPORT_NAMES if name not in exports.EXPORTS]
if missing:
    missing_str = ", ".join(missing)
    raise RuntimeError(f"Missing compat exports: {missing_str}")
