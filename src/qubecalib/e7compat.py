from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np
import numpy.typing as npt

CaptureModule = int


class DspUnit(Enum):
    """DSP feature flags compatible with legacy e7awgsw usage."""

    INTEGRATION = "integration"
    SUM = "sum"
    COMPLEX_FIR = "complex_fir"
    DECIMATION = "decimation"
    COMPLEX_WINDOW = "complex_window"
    CLASSIFICATION = "classification"


@dataclass(frozen=True)
class _WaveData:
    """Container for IQ samples to mimic e7awgsw chunk API."""

    samples: npt.NDArray[np.float32]


@dataclass(frozen=True)
class _WaveChunk:
    """One waveform chunk with post blank and repeat count."""

    wave_data: _WaveData
    num_blank_words: int
    num_repeats: int


class IqWave:
    """Compatibility helper for packing I/Q arrays."""

    @staticmethod
    def convert_to_iq_format(
        i: npt.ArrayLike,
        q: npt.ArrayLike,
        num_samples_in_wave_block: int,
    ) -> npt.NDArray[np.float32]:
        i_arr = np.asarray(i, dtype=np.float32).reshape(-1)
        q_arr = np.asarray(q, dtype=np.float32).reshape(-1)
        if i_arr.shape != q_arr.shape:
            raise ValueError("i and q must have the same shape")
        if num_samples_in_wave_block <= 0:
            raise ValueError("num_samples_in_wave_block must be positive")
        remainder = i_arr.shape[0] % num_samples_in_wave_block
        if remainder:
            pad = num_samples_in_wave_block - remainder
            i_arr = np.pad(i_arr, (0, pad))
            q_arr = np.pad(q_arr, (0, pad))
        return np.column_stack((i_arr, q_arr)).astype(np.float32, copy=False)


class WaveSequence:
    """Minimal legacy-like WaveSequence used by qubecalib internals."""

    NUM_SAMPLES_IN_AWG_WORD = 4
    NUM_SAMPLES_IN_WAVE_BLOCK = 64

    def __init__(self, num_wait_words: int = 0, num_repeats: int = 1) -> None:
        self.num_wait_words = int(num_wait_words)
        self.num_repeats = int(num_repeats)
        self._chunks: list[_WaveChunk] = []

    @property
    def num_chunks(self) -> int:
        return len(self._chunks)

    def add_chunk(
        self,
        *,
        iq_samples: Any,
        num_blank_words: int = 0,
        num_repeats: int = 1,
    ) -> None:
        samples = _normalize_iq_samples(iq_samples)
        self._chunks.append(
            _WaveChunk(
                wave_data=_WaveData(samples=samples),
                num_blank_words=int(num_blank_words),
                num_repeats=int(num_repeats),
            )
        )

    def chunk(self, index: int) -> _WaveChunk:
        return self._chunks[index]


class CaptureParam:
    """Minimal legacy-like CaptureParam used by qubecalib internals."""

    NUM_SAMPLES_IN_ADC_WORD = 4
    NUM_COMPLEX_FIR_COEFS = 16
    MAX_FIR_COEF_VAL = 32767
    NUM_COMPLEXW_WINDOW_COEFS = 2048
    MAX_WINDOW_COEF_VAL = 2147483647

    def __init__(self) -> None:
        self.capture_delay = 0
        self.num_integ_sections = 1
        self.sum_section_list: list[tuple[int, int]] = []
        self.dsp_units_enabled: list[DspUnit] = []
        self.complex_fir_coefs: list[complex] = []
        self.complex_window_coefs: list[complex] = []
        self.classification_params: dict[
            int, tuple[np.float32, np.float32, np.float32]
        ] = {}

    def add_sum_section(self, num_words: int, num_post_blank_words: int = 1) -> None:
        self.sum_section_list.append((int(num_words), int(num_post_blank_words)))

    def sel_dsp_units_to_enable(self, *dsp_units: DspUnit) -> None:
        dedup: list[DspUnit] = []
        for unit in dsp_units:
            if unit not in dedup:
                dedup.append(unit)
        self.dsp_units_enabled = dedup

    def set_decision_func_params(
        self,
        *,
        func_sel: int,
        coef_a: np.float32,
        coef_b: np.float32,
        const_c: np.float32,
    ) -> None:
        self.classification_params[int(func_sel)] = (
            np.float32(coef_a),
            np.float32(coef_b),
            np.float32(const_c),
        )


def _normalize_iq_samples(iq_samples: Any) -> npt.NDArray[np.float32]:
    arr = np.asarray(iq_samples)
    if arr.ndim == 1 and np.iscomplexobj(arr):
        re = np.asarray(np.real(arr), dtype=np.float32)
        im = np.asarray(np.imag(arr), dtype=np.float32)
        return np.column_stack((re, im)).astype(np.float32, copy=False)
    arr = np.asarray(iq_samples, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("iq_samples must be complex array or Nx2 real array")
    return arr
