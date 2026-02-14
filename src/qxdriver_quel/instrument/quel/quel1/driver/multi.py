"""Direct driver primitives for multi-box execution."""

from __future__ import annotations

import datetime
from collections.abc import MutableSequence
from logging import getLogger
from types import MappingProxyType
from typing import Any, Final, NamedTuple, cast

import numpy as np
import numpy.typing as npt
from quel_ic_config import Quel1Box
from quel_ic_config.quel1_wave_subsystem import CaptureReturnCode

from qxdriver_quel.clockmaster_compat import (
    QuBEMasterClient,
    SequencerClient,
    register_box,
)

from . import single
from .single import Quel1PortType

logger = getLogger(__name__)


class NamedBox(NamedTuple):
    """Named box wrapper used by `Quel1System.create`."""

    name: str
    box: Quel1Box


class BoxSetting(NamedTuple):
    """Box-scoped direct settings."""

    name: str
    settings: list[single.AwgSetting | single.RunitSetting | single.TriggerSetting]


class Quel1System:
    """Direct-driver representation of a synchronized multi-box system."""

    def __init__(
        self,
        clockmaster: QuBEMasterClient,
        boxes: MappingProxyType[str, Quel1Box],
    ) -> None:
        self._clockmaster: Final[QuBEMasterClient] = clockmaster
        self._boxes: Final[MappingProxyType[str, Quel1Box]] = boxes
        self.displacement: int = 0
        self.timing_shift: Final[dict[str, int]] = dict.fromkeys(boxes, 0)
        self.config_cache: Final[dict[str, dict[str, Any]]] = {}
        self.monitor_input_ports: Final[dict[str, set[int | tuple[int, int]]]] = {}
        self.config_fetched_at: datetime.datetime | None = None
        self.trigger: dict[
            tuple[str, Quel1PortType],
            tuple[str, Quel1PortType, int],
        ] = {}

    @classmethod
    def create(
        cls,
        *,
        clockmaster: QuBEMasterClient,
        boxes: list[Quel1Box | NamedBox],
        update_copnfig_cache: bool = True,
    ) -> Quel1System:
        """
        Build a `Quel1System` from boxes and optionally fetch config cache.

        Parameters
        ----------
        clockmaster : QuBEMasterClient
            Clock-master client.
        boxes : list[Quel1Box | NamedBox]
            Boxes to include.
        update_copnfig_cache : bool, optional
            Whether to fetch and cache box configuration after creation.

        Returns
        -------
        Quel1System
            Initialized system object.
        """
        boxes_dict: dict[str, Quel1Box] = {}
        for box in boxes:
            if isinstance(box, NamedBox):
                boxes_dict[box.name] = box.box
                register_box(box.box)
            else:
                boxes_dict[str(box.wss.ipaddr_wss)] = box
                register_box(box)
        system = cls(clockmaster, MappingProxyType(boxes_dict))
        if update_copnfig_cache:
            system.update_config_cache()
        return system

    @property
    def boxes(self) -> MappingProxyType[str, Quel1Box]:
        """
        Return boxes in this system.

        Returns
        -------
        MappingProxyType[str, Quel1Box]
            Box map keyed by name.
        """
        return self._boxes

    @property
    def box(self) -> MappingProxyType[str, Quel1Box]:
        """
        Return boxes in this system.

        Returns
        -------
        MappingProxyType[str, Quel1Box]
            Box map keyed by name.
        """
        return self._boxes

    @property
    def clockmaster(self) -> QuBEMasterClient:
        """
        Return the clock-master client.

        Returns
        -------
        QuBEMasterClient
            Clock-master client.
        """
        return self._clockmaster

    def read_clock(self, *box_names: str) -> MutableSequence[tuple[bool, int, int]]:
        """
        Read clocks from sequencer clients for the requested boxes.

        Parameters
        ----------
        box_names : str
            Box names.

        Returns
        -------
        MutableSequence[tuple[bool, int, int]]
            Per-box `(success, current_counter, sysref_counter)` tuples.
        """
        return [
            SequencerClient(
                target_ipaddr=str(self.box[name].wss.ipaddr_sss),
                box=self.box[name],
            ).read_clock()
            for name in box_names
        ]

    def resync(
        self,
        *box_names: str,
    ) -> list[tuple[bool, int] | tuple[str, MutableSequence[tuple[bool, int, int]]]]:
        """
        Synchronize specified boxes and return post-sync clock snapshots.

        Parameters
        ----------
        box_names : str
            Box names. If empty, all boxes are used.

        Returns
        -------
        list[tuple[bool, int] | tuple[str, MutableSequence[tuple[bool, int, int]]]]
            Clock readings for boxes and master.
        """
        if not box_names:
            box_names = tuple(self.boxes.keys())
        master = self.clockmaster
        master.kick_clock_synch(
            [str(self.box[name].wss.ipaddr_sss) for name in box_names]
        )
        return [(name, self.read_clock(name)) for name in box_names] + [
            master.read_clock()
        ]

    def initialize(self, *box_names: str) -> None:
        """
        Initialize AWG/Capture units on specified boxes.

        Parameters
        ----------
        box_names : str
            Box names. If empty, all boxes are used.
        """
        if not box_names:
            box_names = tuple(self.boxes.keys())
        for name in box_names:
            self.box[name].initialize_all_awgunits()
            self.box[name].initialize_all_capunits()

    def update_config_cache(self, *box_names: str) -> None:
        """
        Fetch and refresh box configuration cache.

        Parameters
        ----------
        box_names : str
            Box names. If empty, all boxes are used.
        """
        if not box_names:
            box_names = tuple(self.boxes.keys())
        self.config_cache.clear()
        self.monitor_input_ports.clear()
        for name in box_names:
            self.config_cache[name] = self.box[name].dump_box()
            self.monitor_input_ports[name] = self.box[name].get_monitor_input_ports()
        self.config_fetched_at = datetime.datetime.now()

    def dump_box(self, box_name: str) -> dict[str, Any]:
        """
        Return cached box configuration.

        Parameters
        ----------
        box_name : str
            Box name.

        Returns
        -------
        dict[str, Any]
            Cached box config.
        """
        if self.config_fetched_at is None:
            raise ValueError("config cache is empty")
        if box_name not in self.boxes:
            raise ValueError(f"box {box_name} not found in system")
        return self.config_cache[box_name]

    def dump_port(self, box_name: str, port: Quel1PortType) -> dict[str, Any]:
        """
        Return cached port configuration.

        Parameters
        ----------
        box_name : str
            Box name.
        port : Quel1PortType
            Port index.

        Returns
        -------
        dict[str, Any]
            Cached port config.
        """
        if self.config_fetched_at is None:
            raise ValueError("config cache is empty")
        if box_name not in self.boxes:
            raise ValueError(f"box {box_name} not found in system")
        return self.config_cache[box_name]["ports"][port]

    def is_output_port(self, box_name: str, port: Quel1PortType) -> bool:
        """
        Return whether the given port is output.

        Parameters
        ----------
        box_name : str
            Box name.
        port : Quel1PortType
            Port index.

        Returns
        -------
        bool
            True when output.
        """
        if self.config_fetched_at is None:
            raise ValueError("config cache is empty")
        if box_name not in self.boxes:
            raise ValueError(f"box {box_name} not found in system")
        return self.config_cache[box_name]["ports"][port]["direction"] == "out"

    def is_input_port(self, box_name: str, port: Quel1PortType) -> bool:
        """
        Return whether the given port is input.

        Parameters
        ----------
        box_name : str
            Box name.
        port : Quel1PortType
            Port index.

        Returns
        -------
        bool
            True when input.
        """
        if self.config_fetched_at is None:
            raise ValueError("config cache is empty")
        if box_name not in self.boxes:
            raise ValueError(f"box {box_name} not found in system")
        return self.config_cache[box_name]["ports"][port]["direction"] == "in"

    def get_monitor_input_ports(self, box_name: str) -> set[int | tuple[int, int]]:
        """
        Return monitor input ports for a box.

        Parameters
        ----------
        box_name : str
            Box name.

        Returns
        -------
        set[int | tuple[int, int]]
            Monitor input ports.
        """
        if self.config_fetched_at is None:
            raise ValueError("config cache is empty")
        if box_name not in self.boxes:
            raise ValueError(f"box {box_name} not found in system")
        return self.monitor_input_ports[box_name]

    def get_lo_freq(self, box_name: str, port: Quel1PortType) -> float | None:
        """
        Return LO frequency if present.

        Parameters
        ----------
        box_name : str
            Box name.
        port : Quel1PortType
            Port index.

        Returns
        -------
        float | None
            LO frequency in GHz-equivalent units.
        """
        port_cfg = self.dump_port(box_name, port)
        return cast(float, port_cfg["lo_freq"]) if "lo_freq" in port_cfg else None

    def get_cnco_freq(self, box_name: str, port: Quel1PortType) -> float:
        """
        Return CNCO frequency.

        Parameters
        ----------
        box_name : str
            Box name.
        port : Quel1PortType
            Port index.

        Returns
        -------
        float
            CNCO frequency.
        """
        port_cfg = self.dump_port(box_name, port)
        return cast(float, port_cfg["cnco_freq"])

    def get_fnco_freq(self, box_name: str, port: Quel1PortType, channel: int) -> float:
        """
        Return FNCO frequency for channel/runit.

        Parameters
        ----------
        box_name : str
            Box name.
        port : Quel1PortType
            Port index.
        channel : int
            Channel or runit index.

        Returns
        -------
        float
            FNCO frequency.
        """
        port_cfg = self.dump_port(box_name, port)
        if "channels" in port_cfg:
            key = "channels"
        elif "runits" in port_cfg:
            key = "runits"
        else:
            raise ValueError(
                f"no channel information found in port-{port} of {box_name}"
            )
        ch_cfgs = cast(dict[int, dict[str, float]], port_cfg[key])
        return ch_cfgs[channel]["fnco_freq"]

    def get_sideband(self, box_name: str, port: Quel1PortType) -> str | None:
        """
        Return sideband if present.

        Parameters
        ----------
        box_name : str
            Box name.
        port : Quel1PortType
            Port index.

        Returns
        -------
        str | None
            Sideband label.
        """
        port_cfg = self.dump_port(box_name, port)
        return cast(str, port_cfg["sideband"]) if "sideband" in port_cfg else None


class Quel1SystemCache:
    """Placeholder for future cache abstraction."""


class Action:
    """Executable multi-box direct action with synchronized emission."""

    SYSREF_PERIOD: Final[int] = 2_000
    TIMING_OFFSET: Final[int] = 0
    MIN_TIME_OFFSET = 12_500_000
    DEFAULT_NUM_SYSREF_MEASUREMENTS: Final[int] = 100

    def __init__(
        self,
        quel1system: Quel1System,
        actions: MappingProxyType[str, single.Action],
        estimated_timediff: MappingProxyType[str, int],
        reference_box_name: str,
        ref_sysref_time_offset: int,
    ) -> None:
        self._quel1system: Final[Quel1System] = quel1system
        self._actions: Final[MappingProxyType[str, single.Action]] = actions
        self._estimated_timediff: Final[MappingProxyType[str, int]] = estimated_timediff
        self._reference_box_name: Final[str] = reference_box_name
        self._ref_sysref_time_offset: Final[int] = ref_sysref_time_offset

    @classmethod
    def build(
        cls,
        *,
        quel1system: Quel1System,
        settings: list[BoxSetting],
    ) -> Action:
        """
        Build a synchronized multi-box action from settings.

        Parameters
        ----------
        quel1system : Quel1System
            Target system.
        settings : list[BoxSetting]
            Per-box settings.

        Returns
        -------
        Action
            Built action.
        """
        master = quel1system.clockmaster
        logger.info("clock of master: %s", master.read_clock())

        actions: dict[str, single.Action] = {}
        for box_settings in settings:
            name = box_settings.name
            box = quel1system.box[name]
            current_time = box.get_current_timecounter()
            last_sysref_time = box.get_latest_sysref_timecounter()
            logger.info(
                "clock of %s, current: %s, last sysref: %s, last sysref offset: %s",
                name,
                current_time,
                last_sysref_time,
                cls._mod_by_sysref(last_sysref_time),
            )
            actions[name] = single.Action.build(
                box=box,
                settings=box_settings.settings,
            )

        average_offsets_at_sysref_clock = {
            name: cls._measure_average_offset_at_sysref_clock(action.box)
            for name, action in actions.items()
        }
        reference_box_name = cls._get_reference_box_name(actions)
        ref_sysref_time_offset = average_offsets_at_sysref_clock[reference_box_name]
        estimated_timediff = {
            name: avg_counter - ref_sysref_time_offset
            for name, avg_counter in average_offsets_at_sysref_clock.items()
        }
        for name, timediff in estimated_timediff.items():
            logger.info("estimated time difference of %s: %s", name, timediff)

        return cls(
            quel1system,
            MappingProxyType(actions),
            MappingProxyType(estimated_timediff),
            reference_box_name,
            ref_sysref_time_offset,
        )

    @classmethod
    def _measure_average_offset_at_sysref_clock(
        cls,
        box: Quel1Box,
        num_iters: int | None = None,
    ) -> int:
        """Estimate average SYSREF offset for one box."""
        if num_iters is None:
            num_iters = cls.DEFAULT_NUM_SYSREF_MEASUREMENTS
        offsets = [
            cls._mod_by_sysref(box.get_latest_sysref_timecounter())
            for _ in range(num_iters)
        ]
        return round(sum(offsets) / num_iters)

    @classmethod
    def _get_reference_box_name(cls, actions: dict[str, single.Action]) -> str:
        """Return the first box that contains capture settings."""
        for name, action in actions.items():
            if cls.has_capture_setting(action):
                return name
        raise ValueError("no box has capture setting")

    @staticmethod
    def has_capture_setting(action: single.Action) -> bool:
        """Return True when action contains capture settings."""
        return bool(action.capture_params)

    @classmethod
    def _mod_by_sysref(cls, t: int) -> int:
        """Convert absolute counter into signed SYSREF-period offset."""
        half = cls.SYSREF_PERIOD // 2
        return (t + half) % cls.SYSREF_PERIOD - half

    def capture_start(
        self,
    ) -> dict[str, dict[single.CaptureFutureKey, Any]]:
        """Start capture on boxes that have capture settings."""
        return {
            name: action.capture_start()
            for name, action in self._actions.items()
            if self.has_capture_setting(action)
        }

    def capture_stop(
        self,
        futures: dict[str, dict[single.CaptureFutureKey, Any]],
    ) -> tuple[
        dict[tuple[str, Quel1PortType], CaptureReturnCode],
        dict[tuple[str, Quel1PortType, int], npt.NDArray[np.complex64]],
    ]:
        """
        Resolve capture futures and flatten status/data maps.

        Parameters
        ----------
        futures : dict[str, dict[single.CaptureFutureKey, Any]]
            Per-box capture futures.

        Returns
        -------
        tuple[dict[tuple[str, Quel1PortType], CaptureReturnCode], dict[tuple[str, Quel1PortType, int], NDArray[np.complex64]]]
            Flattened status and IQ maps with box names.
        """
        box_results = {
            name: self._actions[name].capture_stop(future)
            for name, future in futures.items()
        }
        status: dict[tuple[str, Quel1PortType], CaptureReturnCode] = {}
        data: dict[tuple[str, Quel1PortType, int], npt.NDArray[np.complex64]] = {}
        for name, (box_status, box_data) in box_results.items():
            for port, capture_return_code in box_status.items():
                status[(name, port)] = capture_return_code
            for (port, runit), runit_data in box_data.items():
                data[(name, port, runit)] = runit_data
        return status, data

    def action(
        self,
    ) -> tuple[
        dict[tuple[str, Quel1PortType], CaptureReturnCode],
        dict[tuple[str, Quel1PortType, int], npt.NDArray[np.complex64]],
    ]:
        """
        Execute synchronized action and return capture results.

        Returns
        -------
        tuple[dict[tuple[str, Quel1PortType], CaptureReturnCode], dict[tuple[str, Quel1PortType, int], NDArray[np.complex64]]]
            Flattened status and IQ maps with box names.
        """
        futures = self.capture_start()
        self.emit_at(displacement=self._quel1system.displacement)
        return self.capture_stop(futures)

    def emit_at(
        self,
        min_time_offset: int = MIN_TIME_OFFSET,
        displacement: int = 0,
    ) -> None:
        """
        Reserve synchronized emission time and start wave generation.

        Parameters
        ----------
        min_time_offset : int, optional
            Offset from current counter before emission reservation.
        displacement : int, optional
            Additional displacement applied to all boxes.
        """
        for name, action in self._actions.items():
            box = action.box
            last_sysref_time = box.get_latest_sysref_timecounter()
            logger.info(
                "sysref offset of %s: latest: %s",
                name,
                self._mod_by_sysref(last_sysref_time),
            )

        reference_box = self._quel1system.box[self._reference_box_name]
        current_time = reference_box.get_current_timecounter()
        last_sysref_time = reference_box.get_latest_sysref_timecounter()
        logger.info(
            "sysref offset of reference box %s: average: %s, latest: %s",
            self._reference_box_name,
            self._ref_sysref_time_offset,
            self._mod_by_sysref(last_sysref_time),
        )

        fluctuation = (
            self._mod_by_sysref(last_sysref_time) - self._ref_sysref_time_offset
        )
        if abs(fluctuation) > 4:
            logger.warning(
                "large fluctuation (= %s) of sysref is detected from the previous timing measurement",
                fluctuation,
            )

        awgs = {
            name: {(spec.port, spec.channel) for spec in action.wave_sequences}
            for name, action in self._actions.items()
        }

        base_time = current_time + min_time_offset
        align_offset = (16 - (base_time - self._ref_sysref_time_offset) % 16) % 16
        base_time += align_offset + displacement + self.TIMING_OFFSET

        timediff = self._estimated_timediff
        timing_shift = self._quel1system.timing_shift
        tasks = []
        for name, action in self._actions.items():
            if action.trigger_settings or not action.wave_sequences:
                continue
            scheduled_time = base_time + timediff[name] + timing_shift[name]
            tasks.append(
                action.box.start_wavegen(awgs[name], timecounter=scheduled_time)
            )
            logger.info(
                "reserving emission of %s at %s : base_time=%s, timediff=%s, timing_shift=%s",
                name,
                scheduled_time,
                base_time,
                timediff[name],
                timing_shift[name],
            )
        for task in tasks:
            task.result()
