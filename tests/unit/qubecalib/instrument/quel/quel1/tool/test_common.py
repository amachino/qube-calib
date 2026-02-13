"""Tests for QuEL1 tool common sysdb helpers."""

from __future__ import annotations

from qubecalib.instrument.quel.quel1.tool.common import (
    create_sysdb_items_qube_riken_a,
    create_sysdb_items_quel1_riken8,
    define_port_and_channel,
)
from qubecalib.sysconfdb import SystemConfigDatabase


def test_create_sysdb_items_quel1_riken8_respects_box_name_for_pump() -> None:
    """Given a custom box name, when creating quel1-riken8 items, then pump uses that box."""
    sysdb = SystemConfigDatabase()

    create_sysdb_items_quel1_riken8(
        sysdb,
        box_name="BOXA",
        ipaddr_wss="10.0.0.10",
    )

    assert "BOXA.PUMP" in sysdb.port_settings
    assert "Q132SE8.PUMP" not in sysdb.port_settings


def test_define_port_and_channel_uses_default_channel_names() -> None:
    """Given no channel id factory, when defining channels, then suffix-based names are used."""
    sysdb = SystemConfigDatabase()
    sysdb.define_box(
        box_name="BOXB",
        ipaddr_wss="10.0.0.11",
        boxtype="quel1se-riken8",
    )

    port_name = define_port_and_channel(
        sysdb=sysdb,
        box_name="BOXB",
        port_number=3,
        total_channels=2,
        port_id=lambda box_name: f"{box_name}.CTRLX",
    )
    channel_map = dict(sysdb.relation_channel_port)

    assert port_name == "BOXB.CTRLX"
    assert "BOXB.CTRLX0" in channel_map
    assert "BOXB.CTRLX1" in channel_map


def test_create_sysdb_items_qube_riken_a_sets_read_input_ndelay() -> None:
    """Given a custom ndelay, when creating qube-riken-a items, then read input ports use it."""
    sysdb = SystemConfigDatabase()

    create_sysdb_items_qube_riken_a(
        sysdb,
        box_name="BOXC",
        ipaddr_wss="10.0.0.12",
        default_ndelay=11,
    )

    assert sysdb.port_settings["BOXC.READ0.IN"].ndelay_or_nwait == (11, 11, 11, 11)
    assert sysdb.port_settings["BOXC.READ1.IN"].ndelay_or_nwait == (11, 11, 11, 11)
