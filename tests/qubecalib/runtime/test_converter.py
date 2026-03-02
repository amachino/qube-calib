# ruff: noqa

"""Tests for runtime converter helpers."""

from __future__ import annotations

import logging
import warnings
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest
from qxdriver_quel1.pulse import GenSampledSequence, GenSampledSubSequence
from qxdriver_quel1.runtime.converter import Converter
from qxdriver_quel1.sysconf import BoxSetting, PortSetting
from quel_ic_config import QUEL1_BOXTYPE_ALIAS


def test_convert_to_gen_sequence_does_not_mutate_source_waveform() -> None:
    """Given generator conversion, when building device sequences, then source sampled waveform is not mutated."""
    target = "RQ00"
    port = 0
    channel = 0

    source_real = np.array([0.1, -0.2, 0.3])
    source_imag = np.array([0.0, 0.1, -0.1])
    gen_seq = GenSampledSequence(
        target_name=target,
        prev_blank=0,
        post_blank=0,
        repeats=1,
        padding=2,
        sub_sequences=[
            GenSampledSubSequence(
                real=source_real.copy(),
                imag=source_imag.copy(),
                repeats=1,
                post_blank=0,
            )
        ],
    )

    box = BoxSetting(
        box_name="B0",
        ipaddr_wss="127.0.0.1",
        boxtype=next(iter(QUEL1_BOXTYPE_ALIAS.values())),
    )
    port_setting = PortSetting(
        port_name="P0",
        box_name="B0",
        port=port,
        ndelay_or_nwait=(0,),
    )
    resource_map = {
        target: {
            "box": box,
            "port": port_setting,
            "channel_number": channel,
            "target": {"frequency": 5.0},
        }
    }
    # PortConfigAcquirer is only used via attributes in converter methods.
    port_config = {
        target: SimpleNamespace(
            lo_freq=None,
            cnco_freq=5.0e9,
            fnco_freq=0.0,
            sideband="U",
            dump_config={"direction": "out"},
            box_name="B0",
            port=port,
            channel=channel,
        )
    }

    out = Converter.convert_to_gen_device_specific_sequence(
        gen_sampled_sequence={target: gen_seq},
        cap_sampled_sequence={},
        resource_map=resource_map,
        port_config=cast(Any, port_config),
        repeats=1,
        interval=64.0,
    )

    assert ("B0", port, channel) in out
    np.testing.assert_array_equal(gen_seq.sub_sequences[0].real, source_real)
    np.testing.assert_array_equal(gen_seq.sub_sequences[0].imag, source_imag)


def test_calc_modulation_frequency_logs_debug_for_direct_conversion_over_nyquist(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Given direct-conversion frequency above Nyquist, when calculating modulation frequency, then debug is logged and no warning is emitted."""
    port_config = SimpleNamespace(
        lo_freq=None,
        cnco_freq=5.0e9,
        fnco_freq=0.0,
        sideband="U",
        dump_config={"direction": "out"},
        box_name="B0",
        port=0,
        channel=0,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with caplog.at_level(logging.DEBUG, logger="qxdriver_quel1.runtime.converter"):
            freq = Converter.calc_modulation_frequency(
                f_target=5.3,
                port_config=cast(Any, port_config),
            )

    assert freq == pytest.approx(0.3)
    assert not caught
    assert any(
        "Modulation frequency abs(" in rec.getMessage() for rec in caplog.records
    )
    assert any("too high" in rec.getMessage() for rec in caplog.records)


def test_calc_modulation_frequency_logs_debug_for_mixer_output_over_nyquist(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Given mixer output frequency above Nyquist, when calculating modulation frequency, then debug is logged and no warning is emitted."""
    port_config = SimpleNamespace(
        lo_freq=10.0e9,
        cnco_freq=1.0e9,
        fnco_freq=0.0,
        sideband="U",
        dump_config={"direction": "out"},
        box_name="B0",
        port=1,
        channel=0,
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with caplog.at_level(logging.DEBUG, logger="qxdriver_quel1.runtime.converter"):
            freq = Converter.calc_modulation_frequency(
                f_target=11.3,
                port_config=cast(Any, port_config),
            )

    assert freq == pytest.approx(0.3)
    assert not caught
    assert any(
        "Modulation frequency abs(" in rec.getMessage() for rec in caplog.records
    )
    assert any("too high" in rec.getMessage() for rec in caplog.records)


def test_calc_modulation_frequency_infers_missing_sideband_on_mixer_input() -> None:
    """Given mixer input without sideband, when calculating modulation frequency, then smaller-detuning sign is used."""
    port_config = SimpleNamespace(
        lo_freq=9.0e9,
        cnco_freq=1.0e9,
        fnco_freq=0.0,
        sideband=None,
        dump_config={"direction": "in"},
        box_name="B0",
        port=12,
        channel=0,
    )

    freq = Converter.calc_modulation_frequency(
        f_target=10.3,
        port_config=cast(Any, port_config),
    )

    assert freq == pytest.approx(0.3)
