"""System configuration models and builders for quelware-backed calibration."""

from __future__ import annotations

import builtins
import json
import logging
import os
from collections.abc import MutableSequence
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path
from typing import Any, Final

import yaml
from quel_ic_config import (
    QUEL1_BOXTYPE_ALIAS,
    Quel1Box,
    Quel1BoxType,
    Quel1ConfigOption,
)

from .clockmaster_compat import QuBEMasterClient, register_box
from .instrument.quel.quel1 import driver as direct
from .instrument.quel.quel1.driver import Quel1PortType

DEFAULT_SIDEBAND = "U"

logger = logging.getLogger(__name__)


class SystemConfigDatabase:
    """Store and resolve box/port/target relationships for calibration flows."""

    def __init__(self) -> None:
        """Initialize an empty in-memory configuration database."""
        self._clockmaster_setting: ClockmasterSetting | None = None
        self._box_settings: Final[dict[str, BoxSetting]] = {}
        self._box_aliases: Final[dict[str, str]] = {}
        self._port_settings: Final[dict[str, PortSetting]] = {}
        self._relation_channel_target: Final[MutableSequence[tuple[str, str]]] = []
        self._target_settings: Final[dict[str, dict[str, Any]]] = {}
        self._relation_channel_port: Final[
            MutableSequence[tuple[str, dict[str, str | int]]]
        ] = []
        self.timing_shift: Final[dict[str, int]] = {}
        self.skew: Final[dict[str, int]] = {}
        self.port_skew: Final[dict[str, dict[int, int]]] = {}
        self.trigger: dict[
            tuple[str, Quel1PortType], tuple[str, Quel1PortType, int]
        ] = {}
        self.time_to_start: int = 0

    @property
    def box_settings(self) -> dict[str, BoxSetting]:
        """Return configured box settings keyed by box name."""
        return self._box_settings

    @property
    def box_aliases(self) -> dict[str, str]:
        """Return configured box aliases."""
        return self._box_aliases

    @property
    def port_settings(self) -> dict[str, PortSetting]:
        """Return configured port settings keyed by port name."""
        return self._port_settings

    @property
    def clockmaster_setting(self) -> ClockmasterSetting | None:
        """Return clockmaster settings when configured."""
        return self._clockmaster_setting

    @property
    def target_settings(self) -> dict[str, dict[str, Any]]:
        """Return target settings keyed by target name."""
        return self._target_settings

    @property
    def relation_channel_port(
        self,
    ) -> MutableSequence[tuple[str, dict[str, str | int]]]:
        """Return channel-to-port relation records."""
        return self._relation_channel_port

    @property
    def relation_channel_target(self) -> MutableSequence[tuple[str, str]]:
        """Return channel-to-target relation records."""
        return self._relation_channel_target

    def copy(self) -> SystemConfigDatabase:
        """Return a copy of the current instance."""
        return deepcopy(self)

    def define_clockmaster(
        self,
        ipaddr: str,
        reset: bool,
    ) -> None:
        """Set the clockmaster connection settings."""
        self._clockmaster_setting = ClockmasterSetting(
            ipaddr=ipaddr,
            reset=reset,
        )

    def set(
        self,
        clockmaster_setting: dict | None = None,
        box_settings: dict | None = None,
        box_aliases: dict[str, str] | None = None,
        port_settings: dict[str, dict[str, Any]] | None = None,
        relation_channel_target: MutableSequence[tuple[str, str]] | None = None,
        target_settings: dict[str, dict[str, object]] | None = None,
        relation_channel_port: MutableSequence[tuple[str, dict[str, str | int]]]
        | None = None,
    ) -> None:
        """Load partial configuration dictionaries into the current instance."""
        if clockmaster_setting is not None:
            self._clockmaster_setting = ClockmasterSetting(
                ipaddr=clockmaster_setting["ipaddr"],
                reset=clockmaster_setting["reset"],
            )
        if box_settings is not None:
            for box_name, setting in box_settings.items():
                self.add_box_setting(**({"box_name": box_name} | setting))
        if box_aliases is not None:
            for alias, name in box_aliases.items():
                self._box_aliases[alias] = name
        if port_settings is not None:
            for port_name, setting in port_settings.items():
                if setting["box_name"] in self._box_aliases:
                    if not isinstance(setting["box_name"], str):
                        raise ValueError("box_name must be a string")
                    setting["box_name"] = self._box_aliases[setting["box_name"]]
                if "port_name" not in setting:
                    setting["port_name"] = port_name
                if not isinstance(port_name, str):
                    raise TypeError("port_name must be a string")
                # if "port_name" in setting:
                #     raise ValueError(f"port_name must not be in setting '{port_name}'")
                # self.add_port_setting(port_name=port_name, **setting)
                self.add_port_setting(**setting)
        if relation_channel_target is not None:
            for _ in relation_channel_target:
                self._relation_channel_target.append(_)
        if target_settings is not None:
            for target_name, setting in target_settings.items():
                self._target_settings[target_name] = setting
        if relation_channel_port is not None:
            for rcp in relation_channel_port:
                self._relation_channel_port.append(rcp)

    def load(self, path_to_database_file: str | os.PathLike) -> None:
        """Load serialized settings from a JSON database file."""
        with open(Path(os.getcwd()) / Path(path_to_database_file)) as file:
            configs = json.load(file)
        # Keep compatibility with legacy serialized key layout.
        settings = {
            k: v
            for k, v in configs.items()
            if k
            in [
                "clockmaster_setting",
                "box_settings",
                "box_aliases",
                "target_settings",
                "port_settings",
            ]
        }
        relation_channel_target = configs["relation_channel_target"]
        settings["relation_channel_target"] = relation_channel_target
        relation_channel_port = configs["relation_channel_port"]
        settings["relation_channel_port"] = relation_channel_port
        self.set(**settings)

    def load_box_yaml(self, filename: str) -> None:
        """Load box settings from a YAML file."""
        with open(Path(os.getcwd()) / Path(filename)) as file:
            yaml_dict = yaml.safe_load(file)
        self._load_box_yaml(yaml_dict)

    def _load_box_yaml(self, yaml_dict: dict) -> None:
        for name, setting in yaml_dict.items():
            self.add_box_setting(
                box_name=name,
                ipaddr_wss=setting["address"],
                boxtype=setting["type"],
                adapter=setting["adapter"],
            )

    def load_skew_yaml(self, filename: str) -> None:
        """Load skew-related timing settings from a YAML file."""
        with open(Path(os.getcwd()) / Path(filename)) as file:
            yaml_dict = yaml.safe_load(file)
        self._load_skew_yaml(yaml_dict)

    def _load_skew_yaml(self, yaml_dict: dict) -> None:
        for name, setting in yaml_dict["box_setting"].items():
            self.timing_shift[name] = setting["slot"] * 16
            self.skew[name] = setting["wait"]
            # Normalize optional per-port skew map.
            if "port_wait" in setting:
                self.port_skew[name] = {}
                for port, wait in setting["port_wait"].items():
                    if wait < 0:
                        raise ValueError("wait must be non-negative")
                    self.port_skew[name][port] = wait
        self.time_to_start = yaml_dict["time_to_start"]

    def add_box_setting(
        self,
        box_name: str,
        ipaddr_wss: str | IPv4Address | IPv6Address,
        boxtype: Quel1BoxType,
        ipaddr_sss: str | IPv4Address | IPv6Address | None = None,
        ipaddr_css: str | IPv4Address | IPv6Address | None = None,
        config_root: str | os.PathLike | None = None,
        config_options: MutableSequence[Quel1ConfigOption] | None = None,
        adapter: str | None = None,
    ) -> None:
        """Add or replace a box setting entry."""
        if isinstance(boxtype, str):
            boxtype = QUEL1_BOXTYPE_ALIAS[boxtype]
        if config_options is None:
            config_options = []
        self._box_settings[box_name] = BoxSetting(
            box_name=box_name,
            ipaddr_wss=ipaddr_wss,
            boxtype=boxtype,
            ipaddr_sss=ipaddr_sss,
            ipaddr_css=ipaddr_css,
            config_root=config_root,
            config_options=config_options,
            adapter=adapter,
        )

    def add_port_setting(
        self,
        port_name: str,
        box_name: str,
        port: Quel1PortType,
        lo_freq: float = 0,
        cnco_freq: float = 0,
        sideband: str = "",
        vatt: int = 0,
        fnco_freq: tuple[float] | tuple[float, float, float] = (0.0,),
        ndelay_or_nwait: tuple[int, ...] = (),
    ) -> None:
        """Add or replace a port setting entry."""
        self._port_settings[port_name] = PortSetting(
            port_name=port_name,
            box_name=box_name,
            port=port,
            lo_freq=lo_freq,
            cnco_freq=cnco_freq,
            sideband=sideband,
            vatt=vatt,
            fnco_freq=fnco_freq,
            ndelay_or_nwait=ndelay_or_nwait,
        )

    def get_channels_by_target(
        self,
        target_name: str,
    ) -> __builtins__.set[str]:
        """Return channel names bound to the target."""
        return {
            channel
            for channel, target in self._relation_channel_target
            if target == target_name
        }

    def assign_target_to_channel(self, *, target: str, channel: str) -> None:
        """Register a channel-to-target relation."""
        self._relation_channel_target.append((channel, target))

    def append_channel_port_relation(
        self,
        *,
        channel_name: str,
        port_name: str,
        channel_number: int,
    ) -> None:
        """Append a channel-to-port relation entry."""
        self._relation_channel_port.append(
            (
                channel_name,
                {
                    "port_name": port_name,
                    "channel_number": channel_number,
                },
            ),
        )

    def set_target_frequency(self, *, target_name: str, frequency: float) -> None:
        """Set target frequency in GHz."""
        self._target_settings[target_name] = {"frequency": frequency}

    def define_target(
        self,
        target: str,
        *,
        frequency: float = 0,
        channels: list[str] | None = None,
    ) -> None:
        """Define a target and optionally assign channels to it."""
        if target in self._target_settings:
            raise ValueError(f"target {target} is already defined")
        self._target_settings[target] = {"frequency": frequency}
        if channels is not None:
            for channel in channels:
                if (channel, target) not in self._relation_channel_target:
                    self.assign_target_to_channel(channel=channel, target=target)

    def get_channel_numbers_by_target(
        self,
        target_name: str,
    ) -> __builtins__.set[int]:
        """Return channel indices bound to the target."""
        channels = self.get_channels_by_target(target_name)
        channel_port_map = dict(self._relation_channel_port)
        return {
            int(channel_port_map[channel]["channel_number"]) for channel in channels
        }

    def get_channel(
        self,
        channel_name: str,
    ) -> tuple[str, str, int]:
        """Resolve channel metadata as `(box_name, port_name, channel_number)`."""
        port_name = self.get_port_by_channel(channel_name)
        box_name = self._port_settings[port_name].box_name
        channel_number = self.get_channel_number_by_channel(channel_name)
        return box_name, port_name, channel_number

    def get_port_by_channel(self, channel_name: str) -> str:
        """Return the port name assigned to a channel."""
        retval = dict(self._relation_channel_port)[channel_name]["port_name"]
        return retval if isinstance(retval, str) else ""

    def get_channel_number_by_channel(self, channel_name: str) -> int:
        """Return the channel index assigned to a channel name."""
        retval = dict(self._relation_channel_port)[channel_name]["channel_number"]
        return retval if isinstance(retval, int) else 0

    def get_ports_by_target(
        self,
        target_name: str,
    ) -> __builtins__.set[str]:
        """Return port names that contain channels bound to the target."""
        channels = self.get_channels_by_target(target_name)
        channel_port_map = dict(self._relation_channel_port)
        return {str(channel_port_map[channel]["port_name"]) for channel in channels}

    def get_port_numbers_by_target(
        self,
        target_name: str,
    ) -> __builtins__.set[Quel1PortType]:
        """Return physical port identifiers for the target."""
        return {
            self._port_settings[ports].port
            for ports in self.get_ports_by_target(target_name)
        }

    def get_boxes_by_target(
        self,
        target_name: str,
    ) -> __builtins__.set[str]:
        """Return box names that host channels for the target."""
        ports = self.get_ports_by_target(target_name)
        return {self._port_settings[port].box_name for port in ports}

    def define_box(
        self,
        box_name: str,
        ipaddr_wss: str,
        boxtype: str,
        ipaddr_sss: str | None = None,
        ipaddr_css: str | None = None,
        config_root: str | None = None,
        config_options: MutableSequence[Quel1ConfigOption] | None = None,
        adapter: str | None = None,
    ) -> dict[str, object]:
        """Define and store a box setting, then return it as a dictionary."""
        if config_options is None:
            config_options = []
        box_setting = BoxSetting(
            box_name=box_name,
            ipaddr_wss=ipaddr_wss,
            boxtype=QUEL1_BOXTYPE_ALIAS[boxtype],
            config_options=config_options,
            ipaddr_sss=ipaddr_sss,
            ipaddr_css=ipaddr_css,
            config_root=config_root,
            adapter=adapter,
        )
        self._box_settings[box_name] = box_setting
        return box_setting.asdict()

    def define_channel(
        self,
        channel_name: str,
        port_name: str,
        channel_number: int,
        ndelay_or_nwait: int = 0,
    ) -> None:
        """Define a logical channel and update delay/wait settings."""
        self._relation_channel_port.append(
            (
                channel_name,
                {
                    "port_name": port_name,
                    "channel_number": channel_number,
                },
            ),
        )
        _ndelay_or_nwait = list(self._port_settings[port_name].ndelay_or_nwait)
        if channel_number < len(_ndelay_or_nwait):
            _ndelay_or_nwait[channel_number] = ndelay_or_nwait
        else:
            _ = [0 for _ in range(channel_number + 1)]
            for i, v in enumerate(_ndelay_or_nwait):
                _[i] = v
            _[channel_number] = ndelay_or_nwait
            _ndelay_or_nwait = _
        self._port_settings[port_name].ndelay_or_nwait = tuple(_ndelay_or_nwait)

    def define_port(
        self,
        port_name: str,
        box_name: str,
        port_number: Quel1PortType,
        lo_freq: float | None = None,
        cnco_freq: float | None = None,
        sideband: str = DEFAULT_SIDEBAND,
        vatt: int = 0x800,
        fnco_freq: tuple[float]
        | tuple[float, float]
        | tuple[float, float, float]
        | None = None,
        # ndelay_or_nwait: tuple[int, ...] = [],
    ) -> None:
        """Define or update a port configuration entry."""
        if port_name in self._port_settings:
            ndelay_or_nwait = self._port_settings[port_name].ndelay_or_nwait
        else:
            ndelay_or_nwait = ()
        self._port_settings[port_name] = PortSetting(
            port_name=port_name,
            box_name=box_name,
            port=port_number,
            lo_freq=lo_freq,
            cnco_freq=cnco_freq,
            sideband=sideband,
            vatt=vatt,
            fnco_freq=fnco_freq,
            ndelay_or_nwait=ndelay_or_nwait,
        )

    def create_box(
        self,
        box_name: str,
        reconnect: bool = True,
    ) -> Quel1Box:
        """Create and optionally reconnect a `Quel1Box` instance."""
        s = self._box_settings[box_name]
        box = Quel1Box.create(
            ipaddr_wss=str(s.ipaddr_wss),
            ipaddr_sss=str(s.ipaddr_sss),
            ipaddr_css=str(s.ipaddr_css),
            boxtype=s.boxtype,
            skip_init=False,
        )
        register_box(box)
        if reconnect:
            if not all(box.link_status().values()):
                box.relinkup(use_204b=False, background_noise_threshold=350)
            status = box.reconnect()
            for mxfe_idx, _ in status.items():
                if not _:
                    logger.error(
                        f"be aware that mxfe-#{mxfe_idx} is not linked-up properly"
                    )
        return box

    def create_named_box(
        self, box_name: str, *, reconnect: bool = True
    ) -> direct.NamedBox:
        """Create a named box wrapper from configured settings."""
        return direct.NamedBox(
            name=box_name,
            box=self.create_box(
                box_name,
                reconnect=reconnect,
            ),
        )

    def create_quel1system(
        self,
        *box_names: str,
    ) -> direct.Quel1System:
        """Create and initialize a `Quel1System` for the given boxes."""
        if self._clockmaster_setting is None:
            raise ValueError("clock master is not found")
        system = direct.Quel1System.create(
            clockmaster=QuBEMasterClient(str(self._clockmaster_setting.ipaddr)),
            boxes=[self.create_named_box(b, reconnect=True) for b in box_names],
        )
        system.initialize()
        self.refresh_quel1system(system)
        return system

    def refresh_quel1system(self, system: direct.Quel1System) -> direct.Quel1System:
        """Update runtime timing fields on an existing `Quel1System`."""
        # Reuse existing clockmaster and box instances.
        system.trigger = self.trigger
        for box_name, timing_shift in self.timing_shift.items():
            system.timing_shift[box_name] = timing_shift
        system.displacement = self.time_to_start
        return system

    def asdict(self) -> dict[str, object]:
        """Serialize the database to a JSON-compatible dictionary."""
        return {
            "clockmaster_setting": self._clockmaster_setting.asdict()
            if self._clockmaster_setting is not None
            else None,
            "box_settings": {
                box_name: _.asdict() for box_name, _ in self._box_settings.items()
            },
            "box_aliases": self._box_aliases,
            "port_settings": {
                port_name: _.asdict() for port_name, _ in self._port_settings.items()
            },
            "target_settings": self._target_settings,
            "relation_channel_target": self._relation_channel_target,
            "relation_channel_port": self._relation_channel_port,
        }

    def asjson(self) -> str:
        """Serialize the database as formatted JSON text."""
        box_settings = {
            box_name: _.asdict() for box_name, _ in self._box_settings.items()
        }
        for dct in box_settings.values():
            dct["boxtype"] = {v: k for k, v in QUEL1_BOXTYPE_ALIAS.items()}[
                dct["boxtype"]
            ]
        return json.dumps(
            {
                "clockmaster_setting": self._clockmaster_setting.asdict()
                if self._clockmaster_setting is not None
                else None,
                "box_settings": box_settings,
                "box_aliases": self._box_aliases,
                "port_settings": {
                    port_name: _.asdict()
                    for port_name, _ in self._port_settings.items()
                },
                "target_settings": self._target_settings,
                "relation_channel_target": self._relation_channel_target,
                "relation_channel_port": self._relation_channel_port,
            },
            indent=4,
        )

    def get_target_name(
        self,
        *,
        box_name: str,
    ) -> builtins.set[tuple[str, str]]:
        """Return `(target, channel)` pairs hosted by the box."""
        ps = self._port_settings
        port_names = {n for n, s in ps.items() if s.box_name == box_name}
        rcp = self._relation_channel_port
        channel_names = {n for n, c in rcp if c["port_name"] in port_names}
        rct = self._relation_channel_target
        relation_target_channel = {(t, c) for c, t in rct if c in channel_names}
        return relation_target_channel

    def get_targets_by_box(
        self,
        box_name: str,
    ) -> builtins.set[tuple[str, str]]:
        """Return `(target, channel)` pairs for a box."""
        return self.get_target_name(box_name=box_name)

    def get_target_by_port(
        self,
        *,
        box_name: str,
        port: int,
    ) -> builtins.set[tuple[str, str]]:
        """Return `(target, channel)` pairs for a box port."""
        return self.get_targets_by_port(
            box_name=box_name,
            port=port,
        )

    def get_targets_by_port(
        self,
        *,
        box_name: str,
        port: int,
    ) -> builtins.set[tuple[str, str]]:
        """Return `(target, channel)` pairs mapped to a specific port."""
        ps = self._port_settings
        port_names = {
            n for n, s in ps.items() if s.box_name == box_name and s.port == port
        }
        rcp = self._relation_channel_port
        channel_names = {n for n, c in rcp if c["port_name"] in port_names}
        rct = self._relation_channel_target
        relation_target_channel = {(t, c) for c, t in rct if c in channel_names}
        return relation_target_channel

    def get_targets_by_channel(
        self,
        box_name: str,
        port: int,
        channel: int,
    ) -> builtins.set[str]:
        """Return all targets mapped to a specific channel."""
        relation_target_channel = self.get_targets_by_port(box_name=box_name, port=port)
        channels = {c for _, c in relation_target_channel}
        if not channels:
            raise ValueError(
                f"no target is assigned to the channel {box_name, port, channel}"
            )
        try:
            channel_id = {
                p["channel_number"]: c
                for c, p in self._relation_channel_port
                if c in channels
            }[channel]
        except KeyError as err:
            raise ValueError(
                f"invalid channel number {box_name, port, channel}"
            ) from err
        targets = {t for t, c in relation_target_channel if c == channel_id}
        if not targets:
            raise ValueError(
                f"no target is assigned to the channel {box_name, port, channel}"
            )
        return targets

    def get_target_by_channel(
        self,
        box_name: str,
        port: int,
        channel: int,
    ) -> str:
        """Return a single target mapped to a specific channel."""
        relation_target_channel = self.get_target_by_port(box_name=box_name, port=port)
        channels = {c for t, c in relation_target_channel}
        if not channels:
            raise ValueError(
                f"no target is assigned to the channel {box_name, port, channel}"
            )
        try:
            channel_id = {
                p["channel_number"]: c
                for c, p in self._relation_channel_port
                if c in channels
            }[channel]
        except KeyError as err:
            raise ValueError(
                f"invalid channel number {box_name, port, channel}"
            ) from err
        targets = {t for t, c in relation_target_channel if c == channel_id}
        if not targets:
            raise ValueError(
                f"no target is assigned to the channel {box_name, port, channel}"
            )
        return next(iter(targets))


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
