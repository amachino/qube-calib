"""Command-queue execution runtime for `QubeCalib` sessions."""

from __future__ import annotations

import datetime
import getpass
import logging
import os
import time
from collections import deque
from collections.abc import Iterable
from typing import Any, Final, cast

from qubecalib import __version__, neopulse
from qubecalib.clockmaster_compat import SequencerClient, register_box
from qubecalib.instrument.quel.quel1 import driver as direct
from qubecalib.resource_map import ResourceMap, create_target_resource_map
from qubecalib.runtime.box_pool import BoxPool
from qubecalib.sysconfdb import BoxSetting, SystemConfigDatabase

logger = logging.getLogger(__name__)


def _sequencer_type() -> type[Any]:
    """Resolve `Sequencer` lazily to avoid import cycles."""
    from qubecalib.qubecalib import Sequencer

    return Sequencer


def _build_sequencer(
    *,
    gen_sampled_sequence: dict[str, Any],
    cap_sampled_sequence: dict[str, Any],
    resource_map: ResourceMap,
    group_items_by_target: dict[str, Any],
    time_offset: dict[str, int],
    time_to_start: dict[str, int],
    interval: float | None,
    sysdb: SystemConfigDatabase,
    driver: direct.Quel1System | None,
) -> Any:
    """Construct a `Sequencer` lazily to avoid import cycles."""
    sequencer_type = _sequencer_type()
    return sequencer_type(
        gen_sampled_sequence=gen_sampled_sequence,
        cap_sampled_sequence=cap_sampled_sequence,
        resource_map=resource_map,
        group_items_by_target=group_items_by_target,
        time_offset=time_offset,
        time_to_start=time_to_start,
        interval=interval,
        sysdb=sysdb,
        driver=driver,
    )


def _is_sequencer(command: Any) -> bool:
    """Return whether a queued command is a `Sequencer` instance."""
    return isinstance(command, _sequencer_type())


class Executor:
    """
    Queue and execute command objects against a temporary hardware runtime.

    Parameters
    ----------
    sysdb : SystemConfigDatabase
        System configuration database snapshot used by this executor.
    quel1system : direct.Quel1System | None, default=None
        Optional pre-constructed QuEL1 system to reuse for execution.
    """

    def __init__(
        self,
        sysdb: SystemConfigDatabase,
        *,
        quel1system: direct.Quel1System | None = None,
    ) -> None:
        self._work_queue: Final[deque[Any]] = deque()
        self._config_buffer: Final[deque[Any]] = deque()
        self.sysdb = sysdb
        self.quel1system: Final[direct.Quel1System | None] = quel1system
        self._boxpool = BoxPool()
        self.refresh_boxpool()

    def reset(self) -> None:
        """Reset queued commands and recreate the runtime box pool."""
        self._work_queue.clear()
        self.refresh_boxpool()

    def refresh_boxpool(self) -> None:
        """Reinitialize `BoxPool` from the current clock-master setting."""
        self._boxpool = BoxPool()
        clockmaster_setting = self.sysdb.clockmaster_setting
        if clockmaster_setting is not None:
            self._boxpool.create_clock_master(str(clockmaster_setting.ipaddr))

    def collect_boxes(self) -> set[Any]:
        """Collect unique box names referenced by queued sequencer commands."""
        sequencer_type = _sequencer_type()
        return {
            rmap["box"].box_name
            for command in self._work_queue
            if isinstance(command, sequencer_type)
            for rmaps in command.resource_map.values()
            for rmap in rmaps
            if isinstance(rmap["box"], BoxSetting)
        }

    def collect_sequencers(self) -> set[Any]:
        """Collect queued sequencer commands."""
        return {command for command in self._work_queue if _is_sequencer(command)}

    def __iter__(self) -> Executor:
        """Return the iterator itself after clearing prior execution logs."""
        self.clear_log()
        return self

    def __next__(self) -> tuple[Any, dict, dict]:
        """Execute one queued sequencer step and return its capture results."""
        if not self._work_queue:
            self.check_config()
            self._boxpool.clear_box_config_cache()
            self.refresh_boxpool()
            self.clear_log()
            raise StopIteration

        while True:
            if not self._work_queue:
                raise ValueError(
                    "command que should include at least one Sequencer command."
                )
            next_command = self._work_queue.pop()
            if _is_sequencer(next_command):
                break
            next_command.execute(self._boxpool)

        for command in self._work_queue:
            if _is_sequencer(command):
                results = next_command.execute(self._boxpool)
                self._append_execution_log()
                if not self._work_queue:
                    self.check_config()
                    self._boxpool.clear_box_config_cache()
                    self.refresh_boxpool()
                    self.clear_log()
                return results

        results = next_command.execute(self._boxpool)
        self._append_execution_log()
        for command in self._work_queue:
            command.execute(self._boxpool)
        if not self._work_queue:
            self.check_config()
            self._boxpool.clear_box_config_cache()
            self.refresh_boxpool()
            self.clear_log()
        return results

    def _append_execution_log(self) -> None:
        """Append one execution log entry to the in-memory buffer."""
        self._config_buffer.append(
            (
                getpass.getuser(),
                os.path.abspath(__file__),
                __version__,
                datetime.datetime.now(),
                time.clock_gettime_ns(time.CLOCK_REALTIME),
            )
        )

    def check_config(self) -> None:
        """Validate runtime configuration drift."""

    def add_command(self, command: Any) -> None:
        """Queue one command object for execution."""
        self._work_queue.appendleft(command)

    @property
    def command_queue(self) -> deque[Any]:
        """Return the underlying command queue."""
        return self._work_queue

    def clear_command_queue(self) -> None:
        """Clear queued commands without executing them."""
        self._work_queue.clear()

    def get_log(self) -> list[Any]:
        """Return execution log entries as a list."""
        return list(self._config_buffer)

    def clear_log(self) -> None:
        """Clear execution log entries."""
        self._config_buffer.clear()

    def execute(self) -> tuple[str, str, str]:
        """Return a placeholder until batch execution is implemented."""
        return "", "", ""

    def step_execute(
        self,
        repeats: int = 1,
        interval: float = 10240,
        integral_mode: str = "integral",
        dsp_demodulation: bool = True,
        software_demodulation: bool = False,
    ) -> Executor:
        """
        Initialize hardware and return an iterator over queued sequencers.

        Parameters
        ----------
        repeats : int, default=1
            Number of repeated acquisitions per sequence.
        interval : float, default=10240
            Measurement interval in clock ticks.
        integral_mode : str, default="integral"
            Capture mode passed to each sequencer.
        dsp_demodulation : bool, default=True
            Whether to enable DSP demodulation.
        software_demodulation : bool, default=False
            Whether to enable software demodulation.
        """
        boxes = self.collect_boxes()
        clockmaster_setting = self.sysdb.clockmaster_setting
        if len(boxes) > 1 and clockmaster_setting is not None:
            self._boxpool.create_clock_master(ipaddr=str(clockmaster_setting.ipaddr))

        if self.quel1system is None:
            for box_name in boxes:
                setting = self.sysdb.box_settings[box_name]
                box = self._boxpool.create(
                    box_name,
                    ipaddr_wss=str(setting.ipaddr_wss),
                    ipaddr_sss=str(setting.ipaddr_sss),
                    ipaddr_css=str(setting.ipaddr_css),
                    boxtype=setting.boxtype,
                )
                status = box.reconnect()
                for mxfe_idx, linked in status.items():
                    if not linked:
                        logger.error(
                            "be aware that mxfe-#%s is not linked-up properly", mxfe_idx
                        )
        else:
            for box_name in self.quel1system.boxes:
                box = self.quel1system.boxes[box_name]
                register_box(box)
                sqc = SequencerClient(str(box.wss.ipaddr_sss), box=box)
                self._boxpool.register_existing_box(
                    box_name=box_name,
                    box=box,
                    sequencer=sqc,
                )

        for sequencer in self.collect_sequencers():
            new_interval = (
                interval if sequencer.interval is None else sequencer.interval
            )
            sequencer.set_measurement_option(
                repeats=repeats,
                interval=new_interval,
                integral_mode=integral_mode,
                dsp_demodulation=dsp_demodulation,
                software_demodulation=software_demodulation,
            )

        return self

    def _create_target_resource_map(
        self,
        target_names: Iterable[str],
    ) -> ResourceMap:
        """Create a target-to-resource mapping for queued sequence building."""
        return create_target_resource_map(
            sysdb=self.sysdb,
            target_names=target_names,
        )

    def add_sequence(
        self,
        sequence: neopulse.Sequence,
        *,
        driver: direct.Quel1System | None = None,
        interval: float | None = None,
        time_offset: dict[str, int] | None = None,
        time_to_start: dict[str, int] | None = None,
    ) -> None:
        """
        Convert a neopulse sequence and enqueue a corresponding sequencer.

        Parameters
        ----------
        sequence : neopulse.Sequence
            Sequence object to convert and queue.
        driver : direct.Quel1System | None, default=None
            Optional direct driver to execute with instead of pooled boxes.
        interval : float | None, default=None
            Optional per-sequence interval override.
        time_offset : dict[str, int] | None, default=None
            Per-box synchronization offsets.
        time_to_start : dict[str, int] | None, default=None
            Per-box absolute start times in sysref ticks.
        """
        if time_to_start is None:
            time_to_start = {}
        if time_offset is None:
            time_offset = {}
        gen_sampled_sequence, cap_sampled_sequence = (
            sequence.convert_to_sampled_sequence()
        )

        items_by_target = sequence.get_group_items_by_target()
        targets = set(list(gen_sampled_sequence) + list(cap_sampled_sequence))
        resource_map = self._create_target_resource_map(targets)
        self.add_command(
            _build_sequencer(
                gen_sampled_sequence=cast(dict[str, Any], gen_sampled_sequence),
                cap_sampled_sequence=cast(dict[str, Any], cap_sampled_sequence),
                resource_map=resource_map,
                group_items_by_target=cast(dict[str, dict[int, Any]], items_by_target),
                time_offset=time_offset,
                time_to_start=time_to_start,
                interval=interval,
                sysdb=self.sysdb,
                driver=driver,
            )
        )
