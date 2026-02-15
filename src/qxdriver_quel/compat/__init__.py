"""Unified compatibility exports consumed by qubex backend loaders."""

from __future__ import annotations

from quel_ic_config import Quel1Box, Quel1ConfigOption

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
    multi,
    single,
)
from qxdriver_quel.instrument.quel.quel1.tool import Skew
from qxdriver_quel.neopulse import (
    DEFAULT_SAMPLING_PERIOD,
    CapSampledSequence,
    CapSampledSubSequence,
    CaptureSlots,
    GenSampledSequence,
    GenSampledSubSequence,
)
from qxdriver_quel.qubecalib import (
    BoxPool,
    CaptureParamTools,
    Converter,
    QubeCalib,
    Sequencer,
    WaveSequenceTools,
)

MultiAction = multi.Action
SingleAction = single.Action

__all__ = [
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
]
