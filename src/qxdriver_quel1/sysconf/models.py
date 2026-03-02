"""Data models used by system configuration database."""

from __future__ import annotations

import os
from collections.abc import MutableSequence
from dataclasses import asdict, dataclass, field
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Any

from quel_ic_config import QUEL1_BOXTYPE_ALIAS, Quel1BoxType, Quel1ConfigOption

from qxdriver_quel1.driver import Quel1PortType

DEFAULT_SIDEBAND = "U"


@dataclass
class ClockmasterSetting:
    """Clockmaster connection settings."""

    ipaddr: str | IPv4Address | IPv6Address
    reset: bool

    def asdict(self) -> dict[str, object]:
        """Return the setting as a dictionary."""
        return asdict(self)


@dataclass
class BoxSetting:
    """Connection and type settings for one hardware box."""

    box_name: str
    ipaddr_wss: str | IPv4Address | IPv6Address
    boxtype: Quel1BoxType
    ipaddr_sss: str | IPv4Address | IPv6Address | None = None
    ipaddr_css: str | IPv4Address | IPv6Address | None = None
    config_root: str | os.PathLike | None = None
    config_options: MutableSequence[Quel1ConfigOption] = field(default_factory=list)
    adapter: str | None = None

    def __post_init__(self) -> None:
        """Normalize and validate configured IP addresses."""
        if isinstance(self.ipaddr_wss, str):
            self.ipaddr_wss = ip_address(self.ipaddr_wss)
        elif not isinstance(self.ipaddr_wss, (IPv4Address, IPv6Address)):
            raise TypeError("ipaddr_wss should be instance of IPvxAddress")

        if self.ipaddr_sss is None:
            self.ipaddr_sss = self.ipaddr_wss + (1 << 16)
        elif isinstance(self.ipaddr_sss, str):
            self.ipaddr_sss = ip_address(self.ipaddr_sss)
        elif not isinstance(self.ipaddr_sss, (IPv4Address, IPv6Address)):
            raise ValueError("ipaddr_sss should be instance of IPvxAddress")

        if self.ipaddr_css is None:
            self.ipaddr_css = self.ipaddr_wss + (4 << 16)
        elif isinstance(self.ipaddr_css, str):
            self.ipaddr_css = ip_address(self.ipaddr_css)
        elif not isinstance(self.ipaddr_css, (IPv4Address, IPv6Address)):
            raise ValueError("ipaddr_css should be instance of IPvxAddress")

        self.config_options = []

    def asdict(self) -> dict[str, Any]:
        """Return a JSON-friendly dictionary representation."""
        return {
            "ipaddr_wss": str(self.ipaddr_wss),
            "ipaddr_sss": str(self.ipaddr_sss),
            "ipaddr_css": str(self.ipaddr_css),
            "boxtype": self.boxtype,
            "config_root": str(self.config_root)
            if self.config_root is not None
            else None,
            "config_options": self.config_options,
            "adapter": self.adapter,
        }

    def asjsonable(self) -> dict[str, Any]:
        """Return a dictionary with serialized enum aliases."""
        dct = self.asdict()
        dct["boxtype"] = {v: k for k, v in QUEL1_BOXTYPE_ALIAS.items()}[dct["boxtype"]]
        return dct


@dataclass
class PortSetting:
    """Frequency and timing settings for a logical port."""

    port_name: str
    box_name: str
    port: Quel1PortType
    lo_freq: float | None = None  # will be obsolete
    cnco_freq: float | None = None  # will be obsolete
    sideband: str = DEFAULT_SIDEBAND  # will be obsolete
    vatt: int = 0x800  # will be obsolete
    fnco_freq: tuple[float, ...] | None = None  # will be obsolete
    ndelay_or_nwait: tuple[int, ...] = ()

    def asdict(self) -> dict[str, object]:
        """Return a compact dictionary representation."""
        return {
            "port_name": self.port_name,
            "box_name": self.box_name,
            "port": self.port,
            "ndelay_or_nwait": self.ndelay_or_nwait,
        }
