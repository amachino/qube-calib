"""Tests for runtime sequencer capture-result parsing."""

from __future__ import annotations

import numpy as np
from quel_ic_config.quel1_wave_subsystem import CaptureReturnCode
from qxdriver_quel1.driver.capture_result import ClassificationCaptureResult
from qxdriver_quel1.e7awg.compat import CaptureParam, DspUnit
from qxdriver_quel1.runtime.sequencer_core import Sequencer


def test_parse_capture_result_accepts_classification_class_list() -> None:
    """Given direct-driver class-list data, parser should keep DSP labels 1-D."""
    cprm = CaptureParam()
    cprm.sel_dsp_units_to_enable(
        DspUnit.INTEGRATION,
        DspUnit.SUM,
        DspUnit.CLASSIFICATION,
    )
    raw_labels = np.asarray([[0, 3, 0, 3]], dtype=np.uint8)
    status = CaptureReturnCode.SUCCESS

    parsed_status, parsed_data = Sequencer.parse_capture_result(
        object.__new__(Sequencer),
        status,
        ClassificationCaptureResult(labels=(raw_labels,)),
        cprm,
    )

    assert parsed_status is status
    assert len(parsed_data) == 1
    assert parsed_data[0].dtype == np.uint8
    assert parsed_data[0].shape == (4,)
    np.testing.assert_array_equal(parsed_data[0], np.asarray([0, 3, 0, 3]))
