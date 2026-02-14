"""Core calibration orchestration APIs and execution utilities."""

from __future__ import annotations

import functools
import json
import logging
import operator
import os
from collections.abc import Iterable, MutableSequence
from pathlib import Path
from typing import Any, Final

from quel_ic_config import (
    QUEL1_BOXTYPE_ALIAS,
    Quel1Box,
    Quel1BoxType,
    Quel1ConfigOption,
)
from typing_extensions import deprecated

from . import __version__, neopulse
from .clockmaster_compat import QuBEMasterClient, SequencerClient
from .instrument.quel.quel1 import driver as direct
from .resource_map import ResourceMap, create_target_resource_map
from .runtime import sequencer as _sequencer_runtime
from .runtime.box_pool import BoxPool
from .runtime.executor import Executor
from .sysconfdb import SystemConfigDatabase

logger = logging.getLogger(__name__)

Quel1BoxWithRawWss = Quel1Box

Direction = _sequencer_runtime.Direction
Sideband = _sequencer_runtime.Sideband
DEFAULT_SIDEBAND = _sequencer_runtime.DEFAULT_SIDEBAND


class QubeCalib:
    """Orchestrate configuration management and sequence execution."""

    def __init__(
        self,
        path_to_database_file: str | os.PathLike | None = None,
    ) -> None:
        self._system_config_database: Final[SystemConfigDatabase] = (
            SystemConfigDatabase()
        )
        self._executor: Final[Executor] = Executor(self._system_config_database)
        self._box_configs: dict[str, dict[str, Any]] = {}

        if path_to_database_file is not None:
            self.system_config_database.load(path_to_database_file)

    @classmethod
    def from_yaml(
        cls,
        *,
        box_yaml: str = "",
        skew_yaml: str = "",
        clockmaster_ip: str = "",
    ) -> QubeCalib:
        """Build an instance from YAML-based system definitions."""
        self = cls()
        if box_yaml != "":
            self.sysdb.load_box_yaml(box_yaml)
        if skew_yaml != "":
            self.sysdb.load_skew_yaml(skew_yaml)
        if clockmaster_ip != "":
            self.sysdb.define_clockmaster(clockmaster_ip, reset=False)
        return self

    def new_session(self) -> Executor:
        """Create a new session."""
        return Executor(self.system_config_database.copy())

    @property
    def version(self) -> str:
        """Return version."""
        return __version__

    @property
    def system_config_database(self) -> SystemConfigDatabase:
        """Return system config database."""
        return self._system_config_database

    @property
    def sysdb(self) -> SystemConfigDatabase:
        """Return sysdb."""
        return self._system_config_database

    @property
    def executor(self) -> Executor:
        """Return the underlying command executor."""
        return self._executor

    @property
    def Quel1BoxType(self) -> type[Quel1BoxType]:
        """Return Quel1BoxType."""
        return Quel1BoxType

    @deprecated("use sysdb.create_quel1system() instead")
    def create_quel1system(self, box_names: list[str]) -> direct.Quel1System:
        """Create a `Quel1System` from configured box names."""
        return self.sysdb.create_quel1system(*box_names)

    @deprecated("use sysdb.create_quel1system() instead")
    def quel1_create_quel1system(self, *box_names: str) -> direct.Quel1System:
        """Create a `Quel1System` through the direct compatibility path."""
        clockmaster_setting = self.sysdb.clockmaster_setting
        if clockmaster_setting is None:
            raise ValueError("clock master is not found")
        system = direct.Quel1System.create(
            clockmaster=QuBEMasterClient(str(clockmaster_setting.ipaddr)),
            boxes=[self.sysdb.create_named_box(b) for b in box_names],
        )
        return system

    def execute(self) -> tuple:
        """Run queued commands."""
        return self._executor.execute()

    def step_execute(
        self,
        repeats: int = 1,
        interval: float = 10240,
        integral_mode: str = "integral",  # "single"
        dsp_demodulation: bool = True,
        software_demodulation: bool = False,
    ) -> Executor:
        """Prepare runtime state and return an execution iterator."""
        return self._executor.step_execute(
            repeats=repeats,
            interval=interval,
            integral_mode=integral_mode,
            dsp_demodulation=dsp_demodulation,
            software_demodulation=software_demodulation,
        )

    def show_log(
        self,
        name: str = "qxdriver_quel",
        *,
        level: int = logging.DEBUG,
        handler: logging.Handler | None = None,
        formatter: logging.Formatter | None = None,
    ) -> logging.Logger:
        """Configure and return a logger for calibration operations."""
        if handler is None:
            handler = logging.StreamHandler()
        if formatter is None:
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
        handler.setFormatter(formatter)
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(level)
        return logger

    def modify_target_frequency(self, target_name: str, frequency: float) -> None:
        """Update the configured frequency for a target."""
        self.system_config_database.set_target_frequency(
            target_name=target_name,
            frequency=frequency,
        )

    def add_rfswitch(self, box_name: str, port: int, rfswitch: str) -> None:
        """(block / pass), (loop / open)."""
        self._executor.add_command(RfSwitch(box_name, port, rfswitch))

    def add_sequence(
        self,
        sequence: neopulse.Sequence,
        *,
        driver: direct.Quel1System | None = None,
        interval: float | None = None,
        time_offset: dict[str, int] | None = None,  # {box_name: time_offset}
        time_to_start: dict[str, int] | None = None,  # {box_name: time_to_start}
    ) -> None:
        """Convert and queue a sequence for execution."""
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

        self._executor.add_command(
            Sequencer(
                gen_sampled_sequence=gen_sampled_sequence,
                cap_sampled_sequence=cap_sampled_sequence,
                resource_map=resource_map,
                group_items_by_target=items_by_target,
                time_offset=time_offset,
                time_to_start=time_to_start,
                interval=interval,
                sysdb=self.system_config_database,
                driver=driver,
            )
        )

    def define_target(
        self,
        target_name: str,
        channel_name: str,
        target_frequency: float | None = None,
    ) -> None:
        """Define a target mapping and optional frequency."""
        db = self.system_config_database
        db.assign_target_to_channel(target=target_name, channel=channel_name)
        if target_frequency is None and target_name not in db.target_settings:
            raise ValueError(f"frequency of target({target_name}) is not defined")
        if target_frequency is not None:
            db.set_target_frequency(target_name=target_name, frequency=target_frequency)

    def define_clockmaster(
        self,
        ipaddr: str,
        reset: bool,
    ) -> None:
        """Define the clock master endpoint in the system database."""
        return self.system_config_database.define_clockmaster(
            ipaddr,
            reset,
        )

    def define_box(
        self,
        box_name: str,
        ipaddr_wss: str,
        boxtype: str,
        ipaddr_sss: str | None = None,
        ipaddr_css: str | None = None,
        config_root: str | None = None,
        config_options: MutableSequence[Quel1ConfigOption] | None = None,
    ) -> dict[str, Any]:
        """Register one box definition in the system database."""
        if config_options is None:
            config_options = []
        return self.system_config_database.define_box(
            box_name=box_name,
            ipaddr_wss=ipaddr_wss,
            boxtype=boxtype,
            config_options=config_options,
            ipaddr_sss=ipaddr_sss,
            ipaddr_css=ipaddr_css,
            # config_root=config_root,
        )

    def define_channel(
        self,
        channel_name: str,
        port_name: str,
        channel_number: int,
        ndelay_or_nwait: int = 0,
    ) -> None:
        """Bind a logical channel to a physical port channel."""
        self.system_config_database.define_channel(
            channel_name=channel_name,
            port_name=port_name,
            channel_number=channel_number,
            ndelay_or_nwait=ndelay_or_nwait,
        )

    def define_port(
        self,
        port_name: str,
        box_name: str,
        port_number: int,
        lo_freq: float | None = None,
        cnco_freq: float | None = None,
        sideband: str = DEFAULT_SIDEBAND,
        vatt: int = 0x800,
        fnco_freq: tuple[float]
        | tuple[float, float]
        | tuple[float, float, float]
        | None = None,
    ) -> None:
        """Register one logical port mapping."""
        self.system_config_database.define_port(
            port_name=port_name,
            box_name=box_name,
            port_number=port_number,
            lo_freq=lo_freq,
            cnco_freq=cnco_freq,
            sideband=sideband,
            vatt=vatt,
            fnco_freq=fnco_freq,
        )

    def _create_target_resource_map(
        self,
        target_names: Iterable[str],
    ) -> ResourceMap:
        return create_target_resource_map(
            sysdb=self.system_config_database,
            target_names=target_names,
        )

    def get_target_info(self, target_name: str) -> dict:
        """Return metadata for a target."""
        return {
            "box_name": self.system_config_database.get_boxes_by_target(
                target_name=target_name
            ),
            "port": self.system_config_database.get_ports_by_target(
                target_name=target_name
            ),
            "channel": self.system_config_database.get_channel_numbers_by_target(
                target_name=target_name
            ),
            "target_frequency": self.system_config_database.target_settings[
                target_name
            ]["frequency"],
        }

    def get_box_names_by_targets(self, *target_names: str) -> set[str]:
        """Return unique box names that own the given targets."""
        return set(
            functools.reduce(
                operator.iadd,
                [
                    list(self.get_target_info(target_name)["box_name"])
                    for target_name in target_names
                ],
                [],
            )
        )

    def get_box_name_by_alias(self, alias: str) -> str:
        """Resolve a configured box alias."""
        return self.system_config_database.box_aliases[alias]

    def create_box(
        self,
        box_name: str,
        reconnect: bool = True,
    ) -> Quel1BoxWithRawWss:
        """Create and optionally reconnect a box by name."""
        return self.system_config_database.create_box(
            box_name=box_name,
            reconnect=reconnect,
        )

    @deprecated("use sysdb.create_named_box() instead")
    def create_named_box(
        self, box_name: str, *, reconnect: bool = True
    ) -> direct.NamedBox:
        """Create a named-box wrapper for direct driver operations."""
        return direct.NamedBox(
            name=box_name,
            box=self.create_box(
                box_name,
                reconnect=reconnect,
            ),
        )

    def read_clock(self, *box_names: str) -> MutableSequence[tuple[bool, int, int]]:
        """Read clocks from the specified boxes."""
        return [
            SequencerClient(
                target_ipaddr=str(
                    self.system_config_database.box_settings[_].ipaddr_sss
                ),
                box=self.system_config_database.create_box(_, reconnect=False),
            ).read_clock()
            for _ in box_names
        ]

    def resync(
        self, *box_names: str
    ) -> list[tuple[bool, int] | MutableSequence[tuple[bool, int, int]]]:
        """Issue a clock resynchronization and return measured clocks."""
        db = self.system_config_database
        clockmaster_setting = db.clockmaster_setting
        if clockmaster_setting is None:
            raise ValueError("clock master is not found")
        master = QuBEMasterClient(master_ipaddr=str(clockmaster_setting.ipaddr))
        master.kick_clock_synch([str(db.box_settings[_].ipaddr_sss) for _ in box_names])
        return [self.read_clock(_) for _ in box_names] + [master.read_clock()]

    def show_available_boxtype(self) -> MutableSequence[str]:
        """Return available QuEL-1 box-type aliases."""
        return list(QUEL1_BOXTYPE_ALIAS)

    @classmethod
    def quantize_sequence_duration(
        cls,
        sequence_duration: float,
        constrain: float = 10_240,
    ) -> float:
        """Quantize a sequence duration to a hardware-friendly grid."""
        return sequence_duration // constrain * constrain

    def get_all_box_configs(self) -> dict[str, dict[str, Any]]:
        """Return `dump_box()` payloads for all configured boxes."""
        return {
            box_name: self.system_config_database.create_box(box_name).dump_box()
            for box_name in self.system_config_database.box_settings
        }

    def store_all_box_configs(self, path_to_config_file: str | os.PathLike) -> None:
        """Persist current box configurations to a JSON file."""
        with open(Path(os.getcwd()) / Path(path_to_config_file), "w") as fp:
            json.dump(
                self.get_all_box_configs(),
                fp,
                indent=4,
            )

    def load_all_box_configs(self, path_to_config_file: str | os.PathLike) -> None:
        """Load cached box configurations from a JSON file."""
        with open(Path(os.getcwd()) / Path(path_to_config_file)) as fp:
            configs = json.load(fp)
        for _ in configs.values():
            ports: dict[int | tuple[int, int], dict[str, Any]] = {
                int(k): v for k, v in _["ports"].items()
            }
            _["ports"] = ports
            for port_config in ports.values():
                if "channels" in port_config:
                    port_config["channels"] = {
                        int(k): v for k, v in port_config["channels"].items()
                    }
                if "runits" in port_config:
                    port_config["runits"] = {
                        int(k): v for k, v in port_config["runits"].items()
                    }
        self._box_configs = configs

    def apply_all_box_configs(self) -> None:
        """Apply all cached box configurations."""
        for box_name in self._box_configs:
            self._apply_box_config(box_name)

    def _apply_box_config(self, box_name: str) -> None:
        box = self.create_box(box_name)
        box.config_box(self._box_configs[box_name]["ports"])

    def apply_box_config(self, *target_names: str) -> set[str]:
        """Apply cached configurations to boxes that own given targets."""
        box_names = self.get_box_names_by_targets(*target_names)
        for box_name in box_names:
            self._apply_box_config(box_name)
        return box_names

    def clear_command_queue(self) -> None:
        """Clear the executor command queue."""
        self._executor.clear_command_queue()

    def show_command_queue(self) -> MutableSequence:
        """Return the current executor command queue."""
        return self._executor.command_queue

    def create_boxpool(self, *box_names: str) -> BoxPool:
        """Create and initialize a runtime box pool."""
        boxpool = BoxPool()
        clockmaster_setting = self.system_config_database.clockmaster_setting
        if clockmaster_setting is not None:
            boxpool.create_clock_master(
                ipaddr=str(clockmaster_setting.ipaddr),
            )
        for box_name in box_names:
            if box_name not in self.system_config_database.box_settings:
                raise ValueError(f"box({box_name}) is not defined")
            setting = self.system_config_database.box_settings[box_name]
            box = boxpool.create(
                box_name,
                ipaddr_wss=str(setting.ipaddr_wss),
                ipaddr_sss=str(setting.ipaddr_sss),
                ipaddr_css=str(setting.ipaddr_css),
                boxtype=setting.boxtype,
                # config_root=Path(setting.config_root)
                # if setting.config_root is not None
                # else None,
                # config_options=setting.config_options,
            )
            box.reconnect()
        return boxpool


Converter = _sequencer_runtime.Converter
Command = _sequencer_runtime.Command
TargetBPC = _sequencer_runtime.TargetBPC
PortConfigAcquirer = _sequencer_runtime.PortConfigAcquirer
RfSwitch = _sequencer_runtime.RfSwitch
Sequencer = _sequencer_runtime.Sequencer
CaptureParamTools = _sequencer_runtime.CaptureParamTools
WaveSequenceTools = _sequencer_runtime.WaveSequenceTools
