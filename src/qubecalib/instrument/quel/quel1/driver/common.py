"""Common direct-driver entry points for single and multi-box execution."""

from __future__ import annotations

from collections import defaultdict
from typing import Final, NamedTuple

import numpy as np
import numpy.typing as npt
from qubecalib.e7compat import CaptureParam, WaveSequence
from quel_ic_config.quel1_wave_subsystem import CaptureReturnCode

from . import multi, single
from .single import Quel1PortType


class AwgId(NamedTuple):
    """AWG identifier including box name."""

    box: str
    port: Quel1PortType
    channel: int


class RunitId(NamedTuple):
    """Capture runit identifier including box name."""

    box: str
    port: Quel1PortType
    runit: int


class AwgSetting(NamedTuple):
    """AWG programming setting including box scope."""

    awg: AwgId
    wseq: WaveSequence


class RunitSetting(NamedTuple):
    """Capture programming setting including box scope."""

    runit: RunitId
    cprm: CaptureParam


class TriggerSetting(NamedTuple):
    """Trigger mapping from box-scoped AWG to destination port."""

    trigger_awg: AwgId
    triggerd_port: Quel1PortType


def _convert_to_box_setting_dict(
    settings: list[RunitSetting | AwgSetting | TriggerSetting],
) -> dict[str, list[single.AwgSetting | single.RunitSetting | single.TriggerSetting]]:
    """Group common settings by box name and convert to single-box settings."""
    settings_by_box: dict[
        str,
        list[single.AwgSetting | single.RunitSetting | single.TriggerSetting],
    ] = defaultdict(list)
    for setting in settings:
        if isinstance(setting, RunitSetting):
            settings_by_box[setting.runit.box].append(
                single.RunitSetting(
                    single.RunitId(
                        setting.runit.port,
                        setting.runit.runit,
                    ),
                    setting.cprm,
                )
            )
        elif isinstance(setting, AwgSetting):
            settings_by_box[setting.awg.box].append(
                single.AwgSetting(
                    single.AwgId(
                        setting.awg.port,
                        setting.awg.channel,
                    ),
                    setting.wseq,
                )
            )
        elif isinstance(setting, TriggerSetting):
            settings_by_box[setting.trigger_awg.box].append(
                single.TriggerSetting(
                    single.AwgId(
                        setting.trigger_awg.port,
                        setting.trigger_awg.channel,
                    ),
                    setting.triggerd_port,
                )
            )
        else:
            raise TypeError(f"unsupported setting: {setting}")
    return settings_by_box


def _convert_to_box_settings(
    settings: list[RunitSetting | AwgSetting | TriggerSetting],
) -> list[multi.BoxSetting]:
    """Convert flat common settings into box-scoped settings."""
    settings_by_box = _convert_to_box_setting_dict(settings)
    return [
        multi.BoxSetting(name, box_settings)
        for name, box_settings in settings_by_box.items()
    ]


class Action:
    """Wrapper action that dispatches to single-box or multi-box implementation."""

    def __init__(self, action: tuple[str, single.Action] | multi.Action) -> None:
        self._action: Final[tuple[str, single.Action] | multi.Action] = action

    @classmethod
    def build(
        cls,
        *,
        system: multi.Quel1System,
        settings: list[RunitSetting | AwgSetting | TriggerSetting],
    ) -> Action:
        """
        Build an executable action from common settings.

        Parameters
        ----------
        system : multi.Quel1System
            Target system instance.
        settings : list[RunitSetting | AwgSetting | TriggerSetting]
            Box-scoped common settings.

        Returns
        -------
        Action
            Built action object.
        """
        if not settings:
            raise ValueError("no settings provided")
        box_settings = _convert_to_box_settings(settings)
        for setting in box_settings:
            if setting.name not in system.boxes:
                raise ValueError(f"box {setting.name} not found in system")
        if len(box_settings) == 1:
            item = box_settings[0]
            return cls(
                (
                    item.name,
                    single.Action.build(
                        box=system.box[item.name],
                        settings=item.settings,
                    ),
                )
            )
        return cls(multi.Action.build(quel1system=system, settings=box_settings))

    def action(
        self,
    ) -> tuple[
        dict[tuple[str, Quel1PortType], CaptureReturnCode],
        dict[tuple[str, Quel1PortType, int], npt.NDArray[np.complex64]],
    ]:
        """
        Execute and normalize results to box-scoped maps.

        Returns
        -------
        tuple[dict[tuple[str, Quel1PortType], CaptureReturnCode], dict[tuple[str, Quel1PortType, int], NDArray[np.complex64]]]
            Box-prefixed status and IQ data.
        """
        if isinstance(self._action, tuple):
            name, single_action = self._action
            status, data = single_action.action()
            return {(name, key): value for key, value in status.items()}, {
                (name, key[0], key[1]): value for key, value in data.items()
            }
        if isinstance(self._action, multi.Action):
            return self._action.action()
        raise TypeError("invalid action state")
