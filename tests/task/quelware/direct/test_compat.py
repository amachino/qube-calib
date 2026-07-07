# ruff: noqa

from __future__ import annotations

import numpy as np
import pytest
from qxdriver_quel1.e7awg.compat import CaptureParam, DspUnit, WaveSequence
from qxdriver_quel1.driver import classification_param as classification_param_module
from qxdriver_quel1.driver.capture_result import (
    ClassificationCaptureResult,
    read_capture_result,
)
from qxdriver_quel1.driver.compat import (
    convert_captureparam,
    convert_wavesequence,
)
from qxdriver_quel1.driver.e7awghal_classification_patch import (
    RAW_CLASSIFICATION_LINES_ATTR,
    patched_classification_register_builder,
)


def test_convert_wavesequence_keeps_wait_repeat_and_chunks() -> None:
    """Given WaveSequence, conversion preserves wait/repeat/chunk metadata."""
    wseq = WaveSequence(num_wait_words=16, num_repeats=3)
    wseq.add_chunk(iq_samples=[(1, 2)] * 64, num_blank_words=8, num_repeats=2)

    converted = convert_wavesequence(wseq, name_prefix="test")

    assert converted.awg_param.num_wait_word == 16
    assert converted.awg_param.num_repeat == 3
    assert len(converted.awg_param.chunks) == 1
    assert converted.awg_param.chunks[0].num_blank_word == 8
    assert converted.awg_param.chunks[0].num_repeat == 2
    assert converted.awg_param.chunks[0].name_of_wavedata in converted.wavedata
    assert converted.wavedata[converted.awg_param.chunks[0].name_of_wavedata].shape == (
        64,
    )


def test_convert_captureparam_maps_basic_dsp_flags() -> None:
    """Given CaptureParam, conversion maps delay/repeat/flags and sections."""
    cprm = CaptureParam()
    cprm.capture_delay = 32
    cprm.num_integ_sections = 2
    cprm.add_sum_section(12, num_post_blank_words=4)
    cprm.sel_dsp_units_to_enable(DspUnit.DECIMATION)

    converted = convert_captureparam(cprm)

    assert converted.num_wait_word == 32
    assert converted.num_repeat == 2
    assert len(converted.sections) == 1
    assert converted.sections[0].num_capture_word == 12
    assert converted.sections[0].num_blank_word == 4
    assert converted.integration_enable is False
    assert converted.decimation_enable is True


def test_convert_captureparam_scales_complex_fir_coefficients() -> None:
    """Given integer FIR coefficients, conversion rescales for CapParam."""
    cprm = CaptureParam()
    cprm.complex_fir_coefs = [complex(-32768.0, -32768.0)] * 16
    cprm.sel_dsp_units_to_enable(DspUnit.COMPLEX_FIR)

    converted = convert_captureparam(cprm)

    assert np.all(np.real(converted.complexfir_coeff) >= -2.0)
    assert np.all(np.real(converted.complexfir_coeff) < 2.0)
    assert np.all(np.imag(converted.complexfir_coeff) >= -2.0)
    assert np.all(np.imag(converted.complexfir_coeff) < 2.0)


def test_convert_captureparam_scales_window_coefficients() -> None:
    """Given integer window coefficients, conversion rescales for CapParam."""
    cprm = CaptureParam()
    cprm.complex_window_coefs = [complex(-2147483648.0, -2147483648.0)] * 2048
    cprm.sel_dsp_units_to_enable(DspUnit.COMPLEX_WINDOW)

    converted = convert_captureparam(cprm)

    assert np.all(np.real(converted.window_coeff) >= -2.0)
    assert np.all(np.real(converted.window_coeff) < 2.0)
    assert np.all(np.imag(converted.window_coeff) >= -2.0)
    assert np.all(np.imag(converted.window_coeff) < 2.0)


def test_convert_captureparam_maps_identical_classification_lines() -> None:
    """Given identical decision lines, conversion should emit a direct-driver classification param."""
    if classification_param_module.ClassificationParam is None:
        pytest.skip("direct-driver ClassificationParam is not available")

    cprm = CaptureParam()
    cprm.add_sum_section(12, num_post_blank_words=4)
    cprm.sel_dsp_units_to_enable(DspUnit.CLASSIFICATION)
    cprm.set_decision_func_params(
        func_sel=0,
        coef_a=np.float32(1.0),
        coef_b=np.float32(0.0),
        const_c=np.float32(-2.0),
    )
    cprm.set_decision_func_params(
        func_sel=1,
        coef_a=np.float32(1.0),
        coef_b=np.float32(0.0),
        const_c=np.float32(-2.0),
    )

    converted = convert_captureparam(cprm)

    assert converted.classification_enable is True
    assert converted.classification_param.pivot_x == pytest.approx(2.0)
    assert converted.classification_param.pivot_y == pytest.approx(0.0)
    assert converted.classification_param.angle_main == pytest.approx(-90.0)
    assert converted.classification_param.angle_sub == pytest.approx(90.0)


def test_convert_captureparam_preserves_parallel_classification_lines() -> None:
    """Given distinct parallel decision lines, conversion should preserve raw line coefficients."""
    if classification_param_module.ClassificationParam is None:
        pytest.skip("direct-driver ClassificationParam is not available")

    cprm = CaptureParam()
    cprm.add_sum_section(12, num_post_blank_words=4)
    cprm.sel_dsp_units_to_enable(DspUnit.CLASSIFICATION)
    line0 = (np.float32(1.0), np.float32(0.0), np.float32(-2.0))
    line1 = (np.float32(1.0), np.float32(0.0), np.float32(-3.0))
    cprm.set_decision_func_params(
        func_sel=0,
        coef_a=line0[0],
        coef_b=line0[1],
        const_c=line0[2],
    )
    cprm.set_decision_func_params(
        func_sel=1,
        coef_a=line1[0],
        coef_b=line1[1],
        const_c=line1[2],
    )

    converted = convert_captureparam(cprm)

    assert converted.classification_enable is True
    assert getattr(converted, RAW_CLASSIFICATION_LINES_ATTR) == (
        (1.0, 0.0, -2.0),
        (1.0, 0.0, -3.0),
    )


def test_convert_captureparam_patches_parallel_classification_registers() -> None:
    """Given parallel decision lines, conversion should keep distinct register halves."""
    if classification_param_module.ClassificationParam is None:
        pytest.skip("direct-driver ClassificationParam is not available")
    capunit = pytest.importorskip("e7awghal.capunit")

    cprm = CaptureParam()
    cprm.add_sum_section(12, num_post_blank_words=4)
    cprm.sel_dsp_units_to_enable(DspUnit.CLASSIFICATION)
    cprm.set_decision_func_params(
        func_sel=0,
        coef_a=np.float32(1.0),
        coef_b=np.float32(0.0),
        const_c=np.float32(-2.0),
    )
    cprm.set_decision_func_params(
        func_sel=1,
        coef_a=np.float32(1.0),
        coef_b=np.float32(0.0),
        const_c=np.float32(-3.0),
    )

    converted = convert_captureparam(cprm)
    with patched_classification_register_builder(required=True):
        reg_file = capunit._CapParamClassificationRegFile.fromcapparam(converted)

    assert np.asarray(reg_file.p0).tolist() == pytest.approx(
        [32767.0, 0.0, -65534.0]
    )
    assert np.asarray(reg_file.p1).tolist() == pytest.approx(
        [32767.0, 0.0, -98301.0]
    )


def test_patched_classification_register_builder_restores_on_exception() -> None:
    """Given an exception inside the patch scope, fromcapparam should be restored."""
    capunit = pytest.importorskip("e7awghal.capunit")
    reg_file_cls = capunit._CapParamClassificationRegFile
    original = reg_file_cls.fromcapparam
    original_func = getattr(original, "__func__", original)

    with pytest.raises(RuntimeError, match="boom"):
        with patched_classification_register_builder(required=True):
            patched_func = getattr(reg_file_cls.fromcapparam, "__func__")
            assert patched_func is not original_func
            raise RuntimeError("boom")

    restored_func = getattr(reg_file_cls.fromcapparam, "__func__", None)
    assert restored_func is original_func


def test_read_capture_result_uses_class_list_for_classification() -> None:
    """Given classification capture mode, reader conversion should return class-list payloads."""

    class _Reader:
        def as_class_list(self) -> list[np.ndarray]:
            return [np.array([0, 3], dtype=np.uint8)]

        def rawwave(self) -> np.ndarray:
            raise AssertionError

    cprm = CaptureParam()
    cprm.sel_dsp_units_to_enable(DspUnit.CLASSIFICATION)
    payload = read_capture_result(_Reader(), cprm)

    assert isinstance(payload, ClassificationCaptureResult)
    assert len(payload.labels) == 1
    assert np.array_equal(payload.labels[0], np.array([0, 3], dtype=np.uint8))


def test_read_capture_result_returns_rawwave_for_wave_capture() -> None:
    """Given normal capture mode, reader conversion should keep the legacy ndarray payload."""
    rawwave = np.array([1.0 + 2.0j, 3.0 + 4.0j], dtype=np.complex64)

    class _Reader:
        def as_class_list(self) -> list[np.ndarray]:
            raise AssertionError

        def rawwave(self) -> np.ndarray:
            return rawwave

    payload = read_capture_result(_Reader(), CaptureParam())

    assert payload is rawwave
