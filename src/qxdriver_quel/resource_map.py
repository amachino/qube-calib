"""Helpers to resolve target-to-box/port/channel resource mappings."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TypeAlias

from .sysconfdb import BoxSetting, PortSetting, SystemConfigDatabase

ResourceEntry: TypeAlias = dict[str, BoxSetting | PortSetting | int | dict[str, float]]
ResourceMap: TypeAlias = dict[str, list[ResourceEntry]]


def create_target_resource_map(
    *,
    sysdb: SystemConfigDatabase,
    target_names: Iterable[str],
) -> ResourceMap:
    """
    Build a target resource map for sequence conversion.

    Parameters
    ----------
    sysdb : SystemConfigDatabase
        System configuration database containing channel relations.
    target_names : Iterable[str]
        Target names to resolve.

    Returns
    -------
    ResourceMap
        Mapping from target name to resource entries including box, port,
        channel number, and target settings.
    """
    targets_channels = [
        (target_name, sysdb.get_channels_by_target(target_name))
        for target_name in target_names
    ]
    bpc_targets = {
        target_name: [sysdb.get_channel(channel_name) for channel_name in channels]
        for target_name, channels in targets_channels
    }
    return {
        target_name: [
            {
                "box": sysdb.box_settings[box_name],
                "port": sysdb.port_settings[port_name],
                "channel_number": channel_number,
                "target": sysdb.target_settings[target_name],
            }
            for box_name, port_name, channel_number in box_port_channels
        ]
        for target_name, box_port_channels in bpc_targets.items()
    }
