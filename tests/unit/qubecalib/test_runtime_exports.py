"""Runtime module export compatibility tests."""

from qubecalib.qubecalib import BoxPool, Executor
from qubecalib.runtime.box_pool import BoxPool as RuntimeBoxPool
from qubecalib.runtime.executor import Executor as RuntimeExecutor


def test_qubecalib_reexports_runtime_classes() -> None:
    """Given qubecalib runtime modules, when importing legacy paths, then classes are identical."""
    assert Executor is RuntimeExecutor
    assert BoxPool is RuntimeBoxPool
