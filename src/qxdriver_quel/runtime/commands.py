"""Command primitives used by the sequencer runtime."""

from __future__ import annotations

from typing import Any, TypedDict

from quel_ic_config import Quel1Box

from qxdriver_quel import driver as direct
from qxdriver_quel.runtime.box_pool import BoxPool
from qxdriver_quel.sysconf import Quel1PortType


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


def _resolve_sideband(
    *,
    sideband: str | None,
    lo_freq: float | None,
    box_name: str,
    port: Quel1PortType,
    allow_missing_mixer_sideband: bool = False,
) -> str | None:
    """Normalize sideband while preserving direct-conversion behavior."""
    if sideband in {"U", "L"}:
        return sideband
    if sideband is None and lo_freq is None:
        # Direct-conversion transceivers do not require explicit sideband.
        return None
    if sideband is None and allow_missing_mixer_sideband:
        # Some capture input ports expose LO but have no explicit SSB in dump data.
        # In that case, keep None and let converter infer sign from target detuning.
        return None
    if sideband is None:
        raise ValueError(
            f"sideband is missing for mixer-based port {box_name}:{port} (lo_freq={lo_freq})"
        )
    raise ValueError(f"invalid sideband: {sideband}")


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
            is_capture_input = port in box.get_input_ports() and (
                port in box.get_read_input_ports()
                or port in box.get_monitor_input_ports()
            )
            has_loopback_source = False
            sideband_source_port = port
            sideband_source_dump = dp
            if is_capture_input:
                lpbackps = box.get_loopbacks_of_port(port)
                if lpbackps:
                    has_loopback_source = True
                    sideband_source_port = next(iter(lpbackps))
                    sideband_source_dump = dump_box[sideband_source_port]
            sideband = _resolve_sideband(
                sideband=sideband_source_dump.get("sideband"),
                lo_freq=sideband_source_dump.get("lo_freq"),
                box_name=box_name,
                port=sideband_source_port,
                allow_missing_mixer_sideband=is_capture_input
                and not has_loopback_source,
            )
            fnco_freq = 0
            if port in box.get_output_ports():
                fnco_freq = dp["channels"][channel]["fnco_freq"]
            if port in box.get_input_ports():
                fnco_freq = dp["runits"][channel]["fnco_freq"]
            self.lo_freq: float | None = dp.get("lo_freq", None)
            self.cnco_freq: float = dp["cnco_freq"]
            self.fnco_freq: float = fnco_freq
            self.sideband: str | None = sideband
        else:
            self.dump_config = driver.dump_port(box_name, port)
            self.lo_freq = driver.get_lo_freq(box_name, port)
            self.cnco_freq = driver.get_cnco_freq(box_name, port)
            self.fnco_freq = driver.get_fnco_freq(box_name, port, channel)
            is_capture_input = port in box.get_input_ports() and (
                port in box.get_read_input_ports()
                or port in box.get_monitor_input_ports()
            )
            if is_capture_input:
                lpbackps = box.get_loopbacks_of_port(port)
                if lpbackps:
                    lpbackp = next(iter(lpbackps))
                    # Keep capture input SSB aligned with its paired output port.
                    sideband = _resolve_sideband(
                        sideband=driver.get_sideband(box_name, lpbackp),
                        lo_freq=driver.get_lo_freq(box_name, lpbackp),
                        box_name=box_name,
                        port=lpbackp,
                    )
                else:
                    # Some boxes do not define loopback source ports for read inputs.
                    # Keep missing SSB as None to allow converter-side inference.
                    sideband = _resolve_sideband(
                        sideband=driver.get_sideband(box_name, port),
                        lo_freq=self.lo_freq,
                        box_name=box_name,
                        port=port,
                        allow_missing_mixer_sideband=True,
                    )
            else:
                sideband = _resolve_sideband(
                    sideband=driver.get_sideband(box_name, port),
                    lo_freq=self.lo_freq,
                    box_name=box_name,
                    port=port,
                )
            self.sideband = sideband
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
