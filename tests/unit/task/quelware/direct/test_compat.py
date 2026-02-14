from __future__ import annotations

import numpy as np
from qxdriver_quel.e7compat import CaptureParam, DspUnit, WaveSequence
from qxdriver_quel.instrument.quel.quel1.driver.compat import (
    convert_captureparam,
    convert_wavesequence,
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
