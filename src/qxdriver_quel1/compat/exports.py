"""Centralized compatibility exports consumed by qubex driver loader."""

from __future__ import annotations

from quel_ic_config import Quel1Box, Quel1ConfigOption

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
    multi,
    single,
)
from qxdriver_quel1.pulse import (
    DEFAULT_SAMPLING_PERIOD,
    CapSampledSequence,
    CapSampledSubSequence,
    CaptureSlots,
    GenSampledSequence,
    GenSampledSubSequence,
)
from qxdriver_quel1.qubecalib import (
    BoxPool,
    CaptureParamTools,
    Converter,
    QubeCalib,
    Sequencer,
    WaveSequenceTools,
)
from qxdriver_quel1.tool import Skew

MultiAction = multi.Action
SingleAction = single.Action
SingleAwgId = single.AwgId
SingleAwgSetting = single.AwgSetting
SingleRunitId = single.RunitId
SingleRunitSetting = single.RunitSetting
SingleTriggerSetting = single.TriggerSetting


EXPORTS: dict[str, object] = {
    "DEFAULT_SAMPLING_PERIOD": DEFAULT_SAMPLING_PERIOD,
    "Action": Action,
    "AwgId": AwgId,
    "AwgSetting": AwgSetting,
    "BoxPool": BoxPool,
    "CapSampledSequence": CapSampledSequence,
    "CapSampledSubSequence": CapSampledSubSequence,
    "CaptureParamTools": CaptureParamTools,
    "CaptureSlots": CaptureSlots,
    "Converter": Converter,
    "GenSampledSequence": GenSampledSequence,
    "GenSampledSubSequence": GenSampledSubSequence,
    "MultiAction": MultiAction,
    "NamedBox": NamedBox,
    "QuBEMasterClient": QuBEMasterClient,
    "QubeCalib": QubeCalib,
    "Quel1Box": Quel1Box,
    "Quel1ConfigOption": Quel1ConfigOption,
    "Quel1System": Quel1System,
    "RunitId": RunitId,
    "RunitSetting": RunitSetting,
    "Sequencer": Sequencer,
    "SequencerClient": SequencerClient,
    "SingleAction": SingleAction,
    "SingleAwgId": SingleAwgId,
    "SingleAwgSetting": SingleAwgSetting,
    "SingleRunitId": SingleRunitId,
    "SingleRunitSetting": SingleRunitSetting,
    "SingleTriggerSetting": SingleTriggerSetting,
    "Skew": Skew,
    "TriggerSetting": TriggerSetting,
    "WaveSequenceTools": WaveSequenceTools,
}
