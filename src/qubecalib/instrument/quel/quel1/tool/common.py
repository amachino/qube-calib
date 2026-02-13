"""System-config helpers for known QuEL/QuBE box layouts."""

from __future__ import annotations

from collections.abc import Callable

from qubecalib.sysconfdb import SystemConfigDatabase

PortIdFactory = Callable[[str], str]
ChannelIdFactory = Callable[[str, int], str]


def define_port_and_channel(
    sysdb: SystemConfigDatabase,
    box_name: str,
    port_number: int | tuple[int, int],
    total_channels: int,
    port_id: PortIdFactory,
    channel_id: ChannelIdFactory | None = None,
) -> str:
    """
    Define a port and its channels on the system config database.

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
        Function that builds a port name from `box_name`.
    channel_id : ChannelIdFactory | None, optional
        Function that builds channel names from `box_name` and index.

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
    for index in range(total_channels):
        if channel_id is not None:
            channel_name = channel_id(box_name, index)
        else:
            channel_name = f"{port_name}{index}"
        sysdb.define_channel(
            channel_name=channel_name,
            port_name=port_name,
            channel_number=index,
        )
    return port_name


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
    default_ndelay : int, optional
        Default ndelay value for monitor/read ports.
    """
    ndelay = int(default_ndelay)

    sysdb.define_box(
        box_name=box_name,
        ipaddr_wss=ipaddr_wss,
        boxtype="quel1se-riken8",
    )

    port_name = define_port_and_channel(
        sysdb,
        box_name=box_name,
        port_number=0,
        total_channels=4,
        port_id=lambda name: f"{name}.READ.IN",
    )
    sysdb._port_settings[port_name].ndelay_or_nwait = tuple(  # noqa: SLF001
        ndelay for _ in range(4)
    )

    define_port_and_channel(
        sysdb,
        box_name=box_name,
        port_number=1,
        total_channels=1,
        port_id=lambda name: f"{name}.READ.OUT",
    )

    define_port_and_channel(
        sysdb,
        box_name=box_name,
        port_number=(1, 1),
        total_channels=1,
        port_id=lambda name: f"{name}.READ.FOGI.OUT",
    )

    for port_number, monitor_index in [(4, 0), (10, 1)]:
        port_name = define_port_and_channel(
            sysdb,
            box_name=box_name,
            port_number=port_number,
            total_channels=1,
            port_id=lambda name, i=monitor_index: f"{name}.MNTR{i}.IN",
        )
        sysdb._port_settings[port_name].ndelay_or_nwait = (ndelay,)  # noqa: SLF001

    for port_number, control_index, channels in [
        (3, "X", 3),
        (6, 0, 3),
        (7, 1, 3),
        (8, 2, 1),
        (9, 3, 1),
    ]:
        define_port_and_channel(
            sysdb,
            box_name=box_name,
            port_number=port_number,
            total_channels=channels,
            port_id=lambda name, i=control_index: f"{name}.CTRL{i}",
            channel_id=lambda name,
            channel,
            i=control_index: f"{name}.CTRL{i}.CH{channel}",
        )

    define_port_and_channel(
        sysdb,
        box_name="Q132SE8",
        port_number=2,
        total_channels=3,
        port_id=lambda name: f"{name}.PUMP",
        channel_id=lambda name, channel: f"{name}.PUMP.CH{channel}",
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
    default_ndelay : int, optional
        Default ndelay value for monitor/read ports.
    """
    ndelay = int(default_ndelay)

    sysdb.define_box(
        box_name=box_name,
        ipaddr_wss=ipaddr_wss,
        boxtype="qube-riken-a",
    )

    for port_number, read_index in [(0, 0), (13, 1)]:
        define_port_and_channel(
            sysdb,
            box_name=box_name,
            port_number=port_number,
            total_channels=1,
            port_id=lambda name, i=read_index: f"{name}.READ{i}.OUT",
        )

    for port_number, read_index in [(1, 0), (12, 1)]:
        port_name = define_port_and_channel(
            sysdb,
            box_name=box_name,
            port_number=port_number,
            total_channels=4,
            port_id=lambda name, i=read_index: f"{name}.READ{i}.IN",
        )
        sysdb._port_settings[port_name].ndelay_or_nwait = tuple(  # noqa: SLF001
            ndelay for _ in range(4)
        )

    for port_number, pump_index in [(2, 0), (11, 1)]:
        define_port_and_channel(
            sysdb,
            box_name=box_name,
            port_number=port_number,
            total_channels=1,
            port_id=lambda name, i=pump_index: f"{name}.PUMP{i}.OUT",
        )

    for port_number, monitor_index in [(4, 0), (9, 1)]:
        port_name = define_port_and_channel(
            sysdb,
            box_name=box_name,
            port_number=port_number,
            total_channels=1,
            port_id=lambda name, i=monitor_index: f"{name}.MNTR{i}.IN",
        )
        sysdb._port_settings[port_name].ndelay_or_nwait = (ndelay,)  # noqa: SLF001

    for port_number, control_index in [(5, 0), (6, 1), (7, 2), (8, 3)]:
        define_port_and_channel(
            sysdb,
            box_name=box_name,
            port_number=port_number,
            total_channels=3,
            port_id=lambda name, i=control_index: f"{name}.CTRL{i}",
            channel_id=lambda name,
            channel,
            i=control_index: f"{name}.CTRL{i}.CH{channel}",
        )
