"""Tests for runtime command helpers."""

from __future__ import annotations

from typing import Any, cast

import pytest
from qxdriver_quel.runtime.commands import PortConfigAcquirer


class _FakeBox:
    def get_output_ports(self) -> set[int]:
        """Return output ports."""
        return {0}

    def get_input_ports(self) -> set[int]:
        """Return input ports."""
        return {1}

    def get_read_input_ports(self) -> set[int]:
        """Return read input ports."""
        return {1}

    def get_monitor_input_ports(self) -> set[int]:
        """Return monitor input ports."""
        return set()

    def get_loopbacks_of_port(self, port: int) -> set[int]:
        """Return loopback source ports for one input port."""
        return {0} if port == 1 else set()


class _FakeBoxNoLoopback(_FakeBox):
    def get_loopbacks_of_port(self, port: int) -> set[int]:
        """Return no loopback source ports."""
        _ = port
        return set()


class _FakeBoxPool:
    def __init__(self, ports: dict[int, dict[str, Any]]) -> None:
        self._ports = ports

    def ensure_box_config_cache(
        self, *, box_name: str, box: _FakeBox
    ) -> dict[str, Any]:
        """Return one cached box config."""
        _ = box_name
        _ = box
        return {"ports": self._ports}


class _FakeDriver:
    def __init__(
        self,
        *,
        sidebands: dict[int, str | None],
        lo_freqs: dict[int, float | None],
    ) -> None:
        self._sidebands = sidebands
        self._lo_freqs = lo_freqs

    def dump_port(self, box_name: str, port: int) -> dict[str, Any]:
        """Return one dumped port config."""
        _ = box_name
        return {"direction": "in"}

    def get_lo_freq(self, box_name: str, port: int) -> float | None:
        """Return a fixed LO frequency."""
        _ = box_name
        return self._lo_freqs[port]

    def get_cnco_freq(self, box_name: str, port: int) -> float:
        """Return a fixed CNCO frequency."""
        _ = box_name
        _ = port
        return 2.0e9

    def get_fnco_freq(self, box_name: str, port: int, channel: int) -> float:
        """Return a fixed FNCO frequency."""
        _ = box_name
        _ = port
        _ = channel
        return 0.0

    def get_sideband(self, box_name: str, port: int) -> str | None:
        """Return sideband for one port."""
        _ = box_name
        return self._sidebands[port]


def test_port_config_acquirer_uses_loopback_output_sideband_for_input_port() -> None:
    """Given input port, when acquiring config, then sideband follows the paired output port."""
    ports = {
        0: {
            "channels": {0: {"fnco_freq": 0.0}},
            "sideband": "L",
            "lo_freq": 9.0e9,
            "cnco_freq": 1.0e9,
        },
        1: {
            "runits": {0: {"fnco_freq": 0.0}},
            "sideband": None,
            "lo_freq": None,
            "cnco_freq": 1.0e9,
        },
    }
    acquirer = PortConfigAcquirer(
        boxpool=cast(Any, _FakeBoxPool(ports)),
        box_name="B0",
        box=cast(Any, _FakeBox()),
        port=1,
        channel=0,
    )

    assert acquirer.sideband == "L"


def test_port_config_acquirer_raises_when_output_sideband_missing_with_lo() -> None:
    """Given missing output sideband with LO, when acquiring input config, then an error is raised."""
    ports = {
        0: {
            "channels": {0: {"fnco_freq": 0.0}},
            "sideband": None,
            "lo_freq": 9.0e9,
            "cnco_freq": 1.0e9,
        },
        1: {
            "runits": {0: {"fnco_freq": 0.0}},
            "sideband": None,
            "lo_freq": 9.0e9,
            "cnco_freq": 1.0e9,
        },
    }
    with pytest.raises(ValueError, match="sideband is missing"):
        PortConfigAcquirer(
            boxpool=cast(Any, _FakeBoxPool(ports)),
            box_name="B0",
            box=cast(Any, _FakeBox()),
            port=1,
            channel=0,
        )


def test_port_config_acquirer_preserves_none_when_direct_conversion() -> None:
    """Given missing sideband without LO, when acquiring input config, then sideband remains None."""
    ports = {
        0: {
            "channels": {0: {"fnco_freq": 0.0}},
            "sideband": None,
            "lo_freq": None,
            "cnco_freq": 5.0e9,
        },
        1: {
            "runits": {0: {"fnco_freq": 0.0}},
            "sideband": None,
            "lo_freq": None,
            "cnco_freq": 5.0e9,
        },
    }
    acquirer = PortConfigAcquirer(
        boxpool=cast(Any, _FakeBoxPool(ports)),
        box_name="B0",
        box=cast(Any, _FakeBox()),
        port=1,
        channel=0,
    )

    assert acquirer.sideband is None


def test_port_config_acquirer_allows_missing_sideband_on_capture_input_without_loopback() -> (
    None
):
    """Given capture input without loopback and missing sideband, when acquiring config, then sideband remains None."""
    ports = {
        1: {
            "runits": {0: {"fnco_freq": 0.0}},
            "sideband": None,
            "lo_freq": 9.0e9,
            "cnco_freq": 1.0e9,
        },
    }
    acquirer = PortConfigAcquirer(
        boxpool=cast(Any, _FakeBoxPool(ports)),
        box_name="B0",
        box=cast(Any, _FakeBoxNoLoopback()),
        port=1,
        channel=0,
    )

    assert acquirer.sideband is None


def test_port_config_acquirer_uses_loopback_output_sideband_on_driver_path() -> None:
    """Given input port with driver path, when acquiring config, then sideband follows paired output port."""
    acquirer = PortConfigAcquirer(
        boxpool=cast(Any, _FakeBoxPool({})),
        box_name="B0",
        box=cast(Any, _FakeBox()),
        port=1,
        channel=0,
        driver=cast(
            Any,
            _FakeDriver(
                sidebands={
                    0: "L",
                    1: None,
                },
                lo_freqs={
                    0: 9.0e9,
                    1: 9.0e9,
                },
            ),
        ),
    )

    assert acquirer.sideband == "L"


def test_port_config_acquirer_allows_missing_sideband_on_driver_capture_input_without_loopback() -> (
    None
):
    """Given driver capture input without loopback and missing sideband, when acquiring config, then sideband remains None."""
    acquirer = PortConfigAcquirer(
        boxpool=cast(Any, _FakeBoxPool({})),
        box_name="B0",
        box=cast(Any, _FakeBoxNoLoopback()),
        port=1,
        channel=0,
        driver=cast(
            Any,
            _FakeDriver(
                sidebands={
                    1: None,
                },
                lo_freqs={
                    1: 9.0e9,
                },
            ),
        ),
    )

    assert acquirer.sideband is None


def test_port_config_acquirer_raises_when_output_sideband_missing_with_lo_on_driver_path() -> (
    None
):
    """Given missing loopback output sideband with LO on driver path, when acquiring input config, then an error is raised."""
    with pytest.raises(ValueError, match="sideband is missing"):
        PortConfigAcquirer(
            boxpool=cast(Any, _FakeBoxPool({})),
            box_name="B0",
            box=cast(Any, _FakeBox()),
            port=1,
            channel=0,
            driver=cast(
                Any,
                _FakeDriver(
                    sidebands={
                        0: None,
                        1: None,
                    },
                    lo_freqs={
                        0: 9.0e9,
                        1: 9.0e9,
                    },
                ),
            ),
        )
