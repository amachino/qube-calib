"""System-config helpers for known QuEL/QuBE box layouts."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from qxdriver_quel.sysconfdb import SystemConfigDatabase

PortIdFactory = Callable[[str], str]
ChannelIdFactory = Callable[[str, int], str]


@dataclass(frozen=True)
class _PortTemplate:
    """Template for one logical port definition."""

    port_number: int | tuple[int, int]
    total_channels: int
    port_name: str
    channel_name: str | None = None
    set_ndelay: bool = False


def define_port_and_channel(
    sysdb: SystemConfigDatabase,
    box_name: str,
    port_number: int | tuple[int, int],
    total_channels: int,
    port_id: PortIdFactory,
    channel_id: ChannelIdFactory | None = None,
) -> str:
    """
    Define a port and its channels on a system configuration database.

    Parameters
    ----------
    sysdb : SystemConfigDatabase
        Target system configuration database.
    box_name : str
        Box name.
    port_number : int | tuple[int, int]
        Port identifier in box-local numbering.
    total_channels : int
        Number of channels to define on the port.
    port_id : PortIdFactory
        Factory that builds a port name from `box_name`.
    channel_id : ChannelIdFactory | None, optional
        Factory that builds channel names from `box_name` and channel index.
        When omitted, channels are created as `"{port_name}{index}"`.

    Returns
    -------
    str
        Defined port name.
    """
    port_name = port_id(box_name)
    sysdb.define_port(
        port_name=port_name,
        box_name=box_name,
        port_number=port_number,
    )
    for channel in range(total_channels):
        channel_name = (
            channel_id(box_name, channel)
            if channel_id is not None
            else f"{port_name}{channel}"
        )
        sysdb.define_channel(
            channel_name=channel_name,
            port_name=port_name,
            channel_number=channel,
        )
    return port_name


def _set_ndelay(
    *,
    sysdb: SystemConfigDatabase,
    port_name: str,
    total_channels: int,
    ndelay: int,
) -> None:
    """Set fixed ndelay values for all channels on a port."""
    sysdb.port_settings[port_name].ndelay_or_nwait = tuple(
        ndelay for _ in range(total_channels)
    )


def _port_id(template: _PortTemplate) -> PortIdFactory:
    return lambda box_name: template.port_name.format(box=box_name)


def _channel_id(template: _PortTemplate) -> ChannelIdFactory | None:
    pattern = template.channel_name
    if pattern is None:
        return None
    return lambda box_name, channel: pattern.format(
        box=box_name,
        channel=channel,
    )


def _apply_port_templates(
    *,
    sysdb: SystemConfigDatabase,
    box_name: str,
    templates: Iterable[_PortTemplate],
    ndelay: int,
) -> None:
    """Create port/channel entries from templates and optional ndelay settings."""
    for template in templates:
        port_name = define_port_and_channel(
            sysdb=sysdb,
            box_name=box_name,
            port_number=template.port_number,
            total_channels=template.total_channels,
            port_id=_port_id(template),
            channel_id=_channel_id(template),
        )
        if template.set_ndelay:
            _set_ndelay(
                sysdb=sysdb,
                port_name=port_name,
                total_channels=template.total_channels,
                ndelay=ndelay,
            )


def create_sysdb_items_quel1_riken8(
    sysdb: SystemConfigDatabase,
    *,
    box_name: str,
    ipaddr_wss: str,
    default_ndelay: int | str = 7,
) -> None:
    """
    Populate system config entries for a `quel1se-riken8` box.

    Parameters
    ----------
    sysdb : SystemConfigDatabase
        Target system configuration database.
    box_name : str
        Box name.
    ipaddr_wss : str
        WSS IP address.
    default_ndelay : int | str, optional
        Default ndelay value for monitor/read ports.
    """
    ndelay = int(default_ndelay)

    sysdb.define_box(
        box_name=box_name,
        ipaddr_wss=ipaddr_wss,
        boxtype="quel1se-riken8",
    )
    templates = (
        _PortTemplate(0, 4, "{box}.READ.IN", set_ndelay=True),
        _PortTemplate(1, 1, "{box}.READ.OUT"),
        _PortTemplate((1, 1), 1, "{box}.READ.FOGI.OUT"),
        _PortTemplate(4, 1, "{box}.MNTR0.IN", set_ndelay=True),
        _PortTemplate(10, 1, "{box}.MNTR1.IN", set_ndelay=True),
        _PortTemplate(3, 3, "{box}.CTRLX", channel_name="{box}.CTRLX.CH{channel}"),
        _PortTemplate(6, 3, "{box}.CTRL0", channel_name="{box}.CTRL0.CH{channel}"),
        _PortTemplate(7, 3, "{box}.CTRL1", channel_name="{box}.CTRL1.CH{channel}"),
        _PortTemplate(8, 1, "{box}.CTRL2", channel_name="{box}.CTRL2.CH{channel}"),
        _PortTemplate(9, 1, "{box}.CTRL3", channel_name="{box}.CTRL3.CH{channel}"),
        _PortTemplate(2, 3, "{box}.PUMP", channel_name="{box}.PUMP.CH{channel}"),
    )
    _apply_port_templates(
        sysdb=sysdb,
        box_name=box_name,
        templates=templates,
        ndelay=ndelay,
    )


def create_sysdb_items_qube_riken_a(
    sysdb: SystemConfigDatabase,
    *,
    box_name: str,
    ipaddr_wss: str,
    default_ndelay: int | str = 7,
) -> None:
    """
    Populate system config entries for a `qube-riken-a` box.

    Parameters
    ----------
    sysdb : SystemConfigDatabase
        Target system configuration database.
    box_name : str
        Box name.
    ipaddr_wss : str
        WSS IP address.
    default_ndelay : int | str, optional
        Default ndelay value for monitor/read ports.
    """
    ndelay = int(default_ndelay)

    sysdb.define_box(
        box_name=box_name,
        ipaddr_wss=ipaddr_wss,
        boxtype="qube-riken-a",
    )
    templates = (
        _PortTemplate(0, 1, "{box}.READ0.OUT"),
        _PortTemplate(13, 1, "{box}.READ1.OUT"),
        _PortTemplate(1, 4, "{box}.READ0.IN", set_ndelay=True),
        _PortTemplate(12, 4, "{box}.READ1.IN", set_ndelay=True),
        _PortTemplate(2, 1, "{box}.PUMP0.OUT"),
        _PortTemplate(11, 1, "{box}.PUMP1.OUT"),
        _PortTemplate(4, 1, "{box}.MNTR0.IN", set_ndelay=True),
        _PortTemplate(9, 1, "{box}.MNTR1.IN", set_ndelay=True),
        _PortTemplate(5, 3, "{box}.CTRL0", channel_name="{box}.CTRL0.CH{channel}"),
        _PortTemplate(6, 3, "{box}.CTRL1", channel_name="{box}.CTRL1.CH{channel}"),
        _PortTemplate(7, 3, "{box}.CTRL2", channel_name="{box}.CTRL2.CH{channel}"),
        _PortTemplate(8, 3, "{box}.CTRL3", channel_name="{box}.CTRL3.CH{channel}"),
    )
    _apply_port_templates(
        sysdb=sysdb,
        box_name=box_name,
        templates=templates,
        ndelay=ndelay,
    )
