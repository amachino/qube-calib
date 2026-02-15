# ruff: noqa

"""Runtime module export compatibility tests."""

import qxdriver_quel.qubecalib as legacy
from qxdriver_quel.facade import QubeCalib as FacadeQubeCalib
from qxdriver_quel.runtime import commands as runtime_commands
from qxdriver_quel.runtime import sequencer as runtime_sequencer
from qxdriver_quel.runtime.box_pool import BoxPool as RuntimeBoxPool
from qxdriver_quel.runtime.executor import Executor as RuntimeExecutor


def test_qubecalib_reexports_runtime_classes() -> None:
    """Given runtime modules, when importing legacy paths, then re-exports are identical."""
    assert legacy.QubeCalib is FacadeQubeCalib
    assert legacy.Executor is RuntimeExecutor
    assert legacy.BoxPool is RuntimeBoxPool
    assert legacy.Sequencer is runtime_sequencer.Sequencer
    assert legacy.Converter is runtime_sequencer.Converter
    assert legacy.CaptureParamTools is runtime_sequencer.CaptureParamTools
    assert legacy.WaveSequenceTools is runtime_sequencer.WaveSequenceTools
    assert legacy.Command is runtime_commands.Command
    assert legacy.PortConfigAcquirer is runtime_commands.PortConfigAcquirer
    assert legacy.RfSwitch is runtime_commands.RfSwitch
    assert legacy.TargetBPC is runtime_commands.TargetBPC
    assert legacy.Direction is runtime_sequencer.Direction
    assert legacy.Sideband is runtime_sequencer.Sideband
    assert runtime_sequencer.DEFAULT_SIDEBAND == legacy.DEFAULT_SIDEBAND
