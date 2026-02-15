# ruff: noqa

"""Runtime package export tests."""

from qxdriver_quel.runtime import (
    DEFAULT_SIDEBAND,
    BoxPool,
    Converter,
    Direction,
    Executor,
    Sequencer,
    Sideband,
)
from qxdriver_quel.runtime.box_pool import BoxPool as RuntimeBoxPool
from qxdriver_quel.runtime.converter import (
    DEFAULT_SIDEBAND as RuntimeDefaultSideband,
)
from qxdriver_quel.runtime.converter import (
    Converter as RuntimeConverter,
)
from qxdriver_quel.runtime.converter import (
    Direction as RuntimeDirection,
)
from qxdriver_quel.runtime.converter import (
    Sideband as RuntimeSideband,
)
from qxdriver_quel.runtime.executor import Executor as RuntimeExecutor
from qxdriver_quel.runtime.sequencer_core import Sequencer as RuntimeSequencer


def test_runtime_package_reexports_expected_symbols() -> None:
    """Given runtime package imports, when compared to source modules, then symbols match."""
    assert BoxPool is RuntimeBoxPool
    assert Executor is RuntimeExecutor
    assert Sequencer is RuntimeSequencer
    assert Converter is RuntimeConverter
    assert Direction is RuntimeDirection
    assert Sideband is RuntimeSideband
    assert RuntimeDefaultSideband == DEFAULT_SIDEBAND
