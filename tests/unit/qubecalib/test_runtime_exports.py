"""Runtime module export compatibility tests."""

from qubecalib.qubecalib import (
    DEFAULT_SIDEBAND,
    BoxPool,
    CaptureParamTools,
    Converter,
    Direction,
    Executor,
    Sequencer,
    Sideband,
    WaveSequenceTools,
)
from qubecalib.runtime.box_pool import BoxPool as RuntimeBoxPool
from qubecalib.runtime.executor import Executor as RuntimeExecutor
from qubecalib.runtime.sequencer import (
    DEFAULT_SIDEBAND as RuntimeDefaultSideband,
)
from qubecalib.runtime.sequencer import (
    CaptureParamTools as RuntimeCaptureParamTools,
)
from qubecalib.runtime.sequencer import (
    Converter as RuntimeConverter,
)
from qubecalib.runtime.sequencer import (
    Direction as RuntimeDirection,
)
from qubecalib.runtime.sequencer import (
    Sequencer as RuntimeSequencer,
)
from qubecalib.runtime.sequencer import (
    Sideband as RuntimeSideband,
)
from qubecalib.runtime.sequencer import (
    WaveSequenceTools as RuntimeWaveSequenceTools,
)


def test_qubecalib_reexports_runtime_classes() -> None:
    """Given runtime modules, when importing legacy paths, then re-exports are identical."""
    assert Executor is RuntimeExecutor
    assert BoxPool is RuntimeBoxPool
    assert Sequencer is RuntimeSequencer
    assert Converter is RuntimeConverter
    assert CaptureParamTools is RuntimeCaptureParamTools
    assert WaveSequenceTools is RuntimeWaveSequenceTools
    assert Direction is RuntimeDirection
    assert Sideband is RuntimeSideband
    assert RuntimeDefaultSideband == DEFAULT_SIDEBAND
