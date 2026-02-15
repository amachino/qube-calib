"""Command primitives used by the sequencer runtime."""

from __future__ import annotations

from typing import Any, TypedDict

from quel_ic_config import Quel1Box

from qxdriver_quel.instrument.quel.quel1 import driver as direct
from qxdriver_quel.runtime.box_pool import BoxPool
from qxdriver_quel.runtime.converter import DEFAULT_SIDEBAND
from qxdriver_quel.sysconfdb import Quel1PortType


class Command:
    """Define the interface for executable command objects."""

    def execute(
        self,
        boxpool: BoxPool,
    ) -> Any:
        """Run the command against a runtime box pool."""
        pass


class TargetBPC(TypedDict):
    """Describe target mapping with box, port, and channel metadata."""

    box: Quel1Box
    port: int | tuple[int, int]
    channel: int
    box_name: str


class PortConfigAcquirer:
    """Collect port configuration fields used by sequence conversion."""

    def __init__(
        self,
        boxpool: BoxPool,
        box_name: str,
        box: Quel1Box,
        port: Quel1PortType,
        channel: int,
        *,
        driver: direct.Quel1System | None = None,
    ):
        if driver is None:
            # Reuse cached port dump to keep capture/generation conversions cheap.
            dump_box = boxpool.ensure_box_config_cache(
                box_name=box_name,
                box=box,
            )["ports"]
            self.dump_config = dp = dump_box[port]
            sideband = dp.get("sideband", DEFAULT_SIDEBAND)
            fnco_freq = 0
            if port in box.get_output_ports():
                fnco_freq = dp["channels"][channel]["fnco_freq"]
            if port in box.get_input_ports():
                fnco_freq = dp["runits"][channel]["fnco_freq"]
                if (
                    port in box.get_read_input_ports()
                    or port in box.get_monitor_input_ports()
                ):
                    lpbackps = box.get_loopbacks_of_port(port)
                    if lpbackps:
                        lpbackp = next(iter(lpbackps))
                        dumped_port = dump_box[lpbackp]
                        sideband = dumped_port.get("sideband", DEFAULT_SIDEBAND)
            self.lo_freq: float | None = dp.get("lo_freq", None)
            self.cnco_freq: float = dp["cnco_freq"]
            self.fnco_freq: float = fnco_freq
            self.sideband: str = sideband
        else:
            self.dump_config = driver.dump_port(box_name, port)
            self.lo_freq = driver.get_lo_freq(box_name, port)
            self.cnco_freq = driver.get_cnco_freq(box_name, port)
            self.fnco_freq = driver.get_fnco_freq(box_name, port, channel)
            sideband = driver.get_sideband(box_name, port)
            self.sideband = sideband if sideband is not None else DEFAULT_SIDEBAND
        self.box_name = box_name
        self.port = port
        self.channel = channel

    def __repr__(self) -> str:
        """Return a debug representation of acquired port settings."""
        return f"{self.__class__.__name__}(lo_freq={self.lo_freq}, cnco_freq={self.cnco_freq}, fnco_freq={self.fnco_freq}, sideband={self.sideband})"


class RfSwitch(Command):
    """Command that applies RF switch state changes."""

    def __init__(self, box_name: str, port: int, rfswitch: str):
        self._box_name = box_name
        self._port = port
        self._rfswitch = rfswitch

    def execute(
        self,
        boxpool: BoxPool,
    ) -> None:
        """Apply RF switch configuration to a target box port."""
        box = boxpool.get_box(self._box_name)[0]
        box.config_rfswitch(self._port, rfswitch=self._rfswitch)
