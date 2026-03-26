"""Compatibility converters between legacy e7 and `quel_ic_config` types."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import numpy.typing as npt
from e7awghal.classification import ClassificationParam
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


def _normalize_line(
    line: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Return one normalized line representation with stable sign."""
    a, b, c = (float(value) for value in line)
    norm = math.hypot(a, b)
    if norm == 0:
        raise ValueError("Classification line coefficients must not both be zero.")
    a, b, c = a / norm, b / norm, c / norm
    if a < 0 or (np.isclose(a, 0.0) and b < 0):
        a, b, c = -a, -b, -c
    return (a, b, c)


def _line_angle(line: tuple[float, float, float]) -> float:
    """Return the line angle expected by `ClassificationParam`."""
    a, b, _ = (float(value) for value in line)
    if np.isclose(a, 0.0) and np.isclose(b, 0.0):
        raise ValueError("Classification line coefficients must not both be zero.")
    return float(np.degrees(np.arctan2(-a, b)))


def _point_on_line(line: tuple[float, float, float]) -> tuple[float, float]:
    """Return one point on the given line."""
    a, b, c = (float(value) for value in line)
    denom = a * a + b * b
    if denom == 0:
        raise ValueError("Classification line coefficients must not both be zero.")
    return (-a * c / denom, -b * c / denom)


def _lines_share_geometry(
    line0: tuple[float, float, float],
    line1: tuple[float, float, float],
) -> bool:
    """Return whether two line equations represent the same geometric line."""
    return np.allclose(_normalize_line(line0), _normalize_line(line1))


def _intersection_point(
    line0: tuple[float, float, float],
    line1: tuple[float, float, float],
) -> tuple[float, float]:
    """Return the intersection point of two non-parallel lines."""
    a0, b0, c0 = (float(value) for value in line0)
    a1, b1, c1 = (float(value) for value in line1)
    det = a0 * b1 - a1 * b0
    if np.isclose(det, 0.0):
        raise ValueError("Classification lines are parallel and do not intersect.")
    x, y = np.linalg.solve(
        np.array([[a0, b0], [a1, b1]], dtype=np.float64),
        np.array([-c0, -c1], dtype=np.float64),
    )
    return (float(x), float(y))


def _convert_classification_param(cprm: CaptureParam) -> ClassificationParam:
    """Convert legacy line parameters into a direct-driver classification param."""
    try:
        line0 = tuple(float(value) for value in cprm.classification_params[0])
        line1 = tuple(float(value) for value in cprm.classification_params[1])
    except KeyError as exc:
        raise ValueError(
            "Classification DSP requires both decision functions 0 and 1."
        ) from exc

    a0, b0, _ = line0
    a1, b1, _ = line1
    det = a0 * b1 - a1 * b0
    if np.isclose(det, 0.0):
        if not _lines_share_geometry(line0, line1):
            raise ValueError(
                "Parallel classification lines are not supported by direct-driver ClassificationParam conversion."
            )
        pivot_x, pivot_y = _point_on_line(line0)
    else:
        pivot_x, pivot_y = _intersection_point(line0, line1)

    return ClassificationParam(
        pivot_x=pivot_x,
        pivot_y=pivot_y,
        angle_main=_line_angle(line0),
        angle_sub=_line_angle((-line1[0], -line1[1], -line1[2])),
    )


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
    if cap_param.classification_enable:
        cap_param.classification_param = _convert_classification_param(cprm)

    fir_coefs = getattr(cprm, "complex_fir_coefs", None)
    if fir_coefs:
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


def reader_to_capture_data(
    reader: CapIqDataReader,
    *,
    classification_enabled: bool,
) -> Any:
    """Return wave or classified capture payload from one reader."""
    if classification_enabled:
        return reader.as_class_list()
    return reader.rawwave()


def reader_to_flat_wave(reader: CapIqDataReader) -> npt.NDArray[np.complex64]:
    """Return one-dimensional complex waveform from capture reader."""
    return reader.rawwave()
