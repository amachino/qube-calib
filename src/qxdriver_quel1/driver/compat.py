"""Compatibility converters between legacy e7 and `quel_ic_config` types."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
from quel_ic_config import AwgParam, CapIqDataReader, CapParam, CapSection, WaveChunk

from qxdriver_quel1.e7awg.compat import CaptureParam, DspUnit, WaveSequence


@dataclass(frozen=True)
class ConvertedAwgParam:
    """Container for converted AWG params and wavedata payloads."""

    awg_param: AwgParam
    wavedata: dict[str, npt.NDArray[np.complex64]]


def convert_wavesequence(
    wseq: WaveSequence,
    *,
    name_prefix: str,
) -> ConvertedAwgParam:
    """Convert e7awgsw.WaveSequence to e7awghal.AwgParam and wavedata map."""
    awg_param = AwgParam(
        num_wait_word=wseq.num_wait_words,
        num_repeat=wseq.num_repeats,
    )
    wavedata: dict[str, npt.NDArray[np.complex64]] = {}
    for i in range(wseq.num_chunks):
        chunk = wseq.chunk(i)
        name = f"{name_prefix}_chunk_{i}"
        samples = np.asarray(chunk.wave_data.samples, dtype=np.float32)
        iq = np.asarray(samples[:, 0] + 1j * samples[:, 1], dtype=np.complex64)
        wavedata[name] = iq
        awg_param.chunks.append(
            WaveChunk(
                name_of_wavedata=name,
                num_blank_word=chunk.num_blank_words,
                num_repeat=chunk.num_repeats,
            )
        )
    return ConvertedAwgParam(awg_param=awg_param, wavedata=wavedata)


def convert_captureparam(cprm: CaptureParam) -> CapParam:
    """Convert e7awgsw.CaptureParam to e7awghal.CapParam."""
    cap_param = CapParam(
        num_wait_word=cprm.capture_delay,
        num_repeat=cprm.num_integ_sections,
        sections=[
            CapSection(
                name=f"s{i}",
                num_capture_word=num_capture_word,
                num_blank_word=max(1, num_blank_word),
            )
            for i, (num_capture_word, num_blank_word) in enumerate(
                cprm.sum_section_list
            )
        ],
    )

    dsp_enabled = set(cprm.dsp_units_enabled)
    cap_param.integration_enable = DspUnit.INTEGRATION in dsp_enabled
    cap_param.sum_enable = DspUnit.SUM in dsp_enabled
    cap_param.complexfir_enable = DspUnit.COMPLEX_FIR in dsp_enabled
    cap_param.decimation_enable = DspUnit.DECIMATION in dsp_enabled
    cap_param.window_enable = DspUnit.COMPLEX_WINDOW in dsp_enabled
    cap_param.classification_enable = DspUnit.CLASSIFICATION in dsp_enabled

    fir_coefs = getattr(cprm, "complex_fir_coefs", None)
    if fir_coefs:
        # e7awgsw stores FIR coefficients as fixed-point-like integers, while
        # quel_ic_config.CapParam expects normalized float coefficients.
        # Convert by exponent offset and clamp to the accepted range [-2.0, 2.0).
        fir = np.asarray(fir_coefs, dtype=np.complex64)
        fir_scale = float(1 << cap_param.complexfir_exponent_offset)
        fir_lower = np.float32(-2.0)
        fir_upper = np.nextafter(np.float32(2.0), np.float32(0.0))
        fir_real = np.clip(np.real(fir) / fir_scale, fir_lower, fir_upper)
        fir_imag = np.clip(np.imag(fir) / fir_scale, fir_lower, fir_upper)
        cap_param.complexfir_coeff = np.asarray(
            fir_real + 1j * fir_imag,
            dtype=np.complex64,
        )
    window_coefs = getattr(cprm, "complex_window_coefs", None)
    if window_coefs:
        # e7awgsw window coefficients are also integer-scaled values.
        # CapParam validates normalized coefficients in [-2.0, 2.0), so rescale
        # by 2^30 and clamp for backend compatibility.
        window = np.asarray(window_coefs, dtype=np.complex128)
        window_scale = float(1 << 30)
        window_lower = np.float64(-2.0)
        window_upper = np.nextafter(np.float64(2.0), np.float64(0.0))
        window_real = np.clip(
            np.real(window) / window_scale, window_lower, window_upper
        )
        window_imag = np.clip(
            np.imag(window) / window_scale, window_lower, window_upper
        )
        cap_param.window_coeff = np.asarray(
            window_real + 1j * window_imag,
            dtype=np.complex128,
        )
    return cap_param


def reader_to_flat_wave(reader: CapIqDataReader) -> npt.NDArray[np.complex64]:
    """Return one-dimensional complex waveform from capture reader."""
    return reader.rawwave()
