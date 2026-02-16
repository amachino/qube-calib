"""Tests for runtime command helpers."""

from __future__ import annotations

from typing import Any, cast

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
    def dump_port(self, box_name: str, port: int) -> dict[str, Any]:
        """Return one dumped port config."""
        _ = box_name
        _ = port
        return {"direction": "in"}

    def get_lo_freq(self, box_name: str, port: int) -> float | None:
        """Return a fixed LO frequency."""
        _ = box_name
        _ = port
        return None

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
        """Return sideband as None."""
        _ = box_name
        _ = port
        return None


def test_port_config_acquirer_keeps_none_sideband_on_boxpool_path() -> None:
    """Given None sideband in cache, when acquiring capture-port config, then sideband stays None."""
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

    assert acquirer.sideband is None


def test_port_config_acquirer_keeps_none_sideband_on_driver_path() -> None:
    """Given None sideband from driver, when acquiring config, then sideband stays None."""
    acquirer = PortConfigAcquirer(
        boxpool=cast(Any, _FakeBoxPool({})),
        box_name="B0",
        box=cast(Any, _FakeBox()),
        port=1,
        channel=0,
        driver=cast(Any, _FakeDriver()),
    )

    assert acquirer.sideband is None
