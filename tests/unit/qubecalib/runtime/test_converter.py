"""Tests for runtime converter helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import numpy as np
from qxdriver_quel.neopulse import GenSampledSequence, GenSampledSubSequence
from qxdriver_quel.runtime.converter import Converter
from qxdriver_quel.sysconfdb import BoxSetting, PortSetting
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
