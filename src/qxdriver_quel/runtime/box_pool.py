"""Hardware box registry and low-level connection helpers."""

from __future__ import annotations

import logging
from typing import Any, Final, cast

from quel_ic_config import Quel1Box, Quel1BoxType

from qxdriver_quel.clockmaster_compat import (
    QuBEMasterClient,
    SequencerClient,
    register_box,
)
from qxdriver_quel.sysconfdb import Quel1PortType

logger = logging.getLogger(__name__)

Quel1BoxWithRawWss = Quel1Box


class BoxPool:
    """
    Hold connected QuEL-1 boxes and shared per-box runtime state.

    Notes
    -----
    This class owns short-lived runtime objects used during a single
    execution session, such as sequencer clients and cached `dump_box()`
    snapshots.
    """

    SYSREF_PERIOD: int = 2_000
    DEFAULT_NUM_SYSREF_MEASUREMENTS: Final[int] = 100

    def __init__(self) -> None:
        self._clock_master: QuBEMasterClient | None = None
        self._boxes: dict[str, tuple[Quel1BoxWithRawWss, SequencerClient]] = {}
        self._linkstatus: dict[str, bool] = {}
        self._estimated_timediff: dict[str, int] = {}
        self._cap_sysref_time_offset: int = 0
        self._port_direction: dict[tuple[str, Quel1PortType], str] = {}
        self._box_config_cache: dict[str, dict] = {}

    @property
    def clock_master(self) -> QuBEMasterClient | None:
        """Return the configured clock master client."""
        return self._clock_master

    @property
    def boxes(self) -> dict[str, tuple[Quel1BoxWithRawWss, SequencerClient]]:
        """Return registered boxes and their sequencer clients."""
        return self._boxes

    @property
    def box_config_cache(self) -> dict[str, dict]:
        """Return cached `dump_box()` payloads by box name."""
        return self._box_config_cache

    def register_existing_box(
        self,
        *,
        box_name: str,
        box: Quel1BoxWithRawWss,
        sequencer: SequencerClient,
    ) -> None:
        """Register an externally created box and sequencer pair."""
        self._boxes[box_name] = (box, sequencer)
        self._linkstatus[box_name] = False

    def ensure_box_config_cache(
        self,
        *,
        box_name: str,
        box: Quel1BoxWithRawWss,
    ) -> dict[str, Any]:
        """Return cached dump data for a box, creating it on first use."""
        if box_name not in self._box_config_cache:
            self._box_config_cache[box_name] = box.dump_box()
        return self._box_config_cache[box_name]

    def clear_box_config_cache(self) -> None:
        """Clear cached dump-box payloads."""
        self._box_config_cache.clear()

    def replace_box_config_cache(self, box_configs: dict[str, Any]) -> None:
        """Replace cached `dump_box()` payloads."""
        self._box_config_cache = {
            box_name: cast(dict, config) for box_name, config in box_configs.items()
        }

    def update_box_config_cache(self, box_configs: dict[str, Any]) -> None:
        """Update cached `dump_box()` payloads by key."""
        for box_name, config in box_configs.items():
            self._box_config_cache[box_name] = cast(dict, config)

    def create_clock_master(
        self,
        ipaddr: str,
    ) -> None:
        """Create a clock-master client."""
        self._clock_master = QuBEMasterClient(master_ipaddr=ipaddr)

    def measure_timediff(
        self, num_iters: int = DEFAULT_NUM_SYSREF_MEASUREMENTS
    ) -> tuple[str, int]:
        """Measure average sysref tick offset across registered boxes."""
        sqcs = {name: sqc for name, (_, sqc) in self._boxes.items()}
        counter_at_sysref_clk = dict.fromkeys(self._boxes, 0)
        for _ in range(num_iters):
            for name, sqc in sqcs.items():
                measurement = sqc.read_clock()
                if len(measurement) < 2:
                    raise RuntimeError("firmware doesn't support this measurement")
                counter_at_sysref_clk[name] += measurement[2] % self.SYSREF_PERIOD

        avg: dict[str, int] = {
            name: round(counter / num_iters)
            for name, counter in counter_at_sysref_clk.items()
        }
        refname = next(iter(self._boxes.keys()))
        adj = avg[refname]
        self._estimated_timediff = {
            name: counter - adj for name, counter in avg.items()
        }
        self._cap_sysref_time_offset = avg[refname]
        return refname, avg[refname]

    def create(
        self,
        box_name: str,
        *,
        ipaddr_wss: str,
        ipaddr_sss: str,
        ipaddr_css: str,
        boxtype: Quel1BoxType,
    ) -> Quel1BoxWithRawWss:
        """Create and register a new box and its sequencer client."""
        box = Quel1BoxWithRawWss.create(
            ipaddr_wss=ipaddr_wss,
            ipaddr_sss=ipaddr_sss,
            ipaddr_css=ipaddr_css,
            boxtype=boxtype,
            skip_init=False,
        )
        register_box(box)
        sqc = SequencerClient(ipaddr_sss, box=box)
        self._boxes[box_name] = (box, sqc)
        self._linkstatus[box_name] = False
        return box

    def init(self, reconnect: bool = True, resync: bool = True) -> None:
        """Initialize box links and AWGs for the current session."""
        self.scan_link_status(reconnect=reconnect)
        self.reset_awg()
        if self._clock_master is None:
            return

        _ = resync

    def scan_link_status(
        self,
        reconnect: bool = False,
    ) -> None:
        """Scan and cache link status for every registered box."""
        for name, (box, _sqc) in self._boxes.items():
            link_status = True
            if reconnect:
                if not all(box.reconnect().values()):
                    if all(
                        box.reconnect(
                            ignore_crc_error_of_mxfe=box.css.get_all_groups()
                        ).values()
                    ):
                        logger.warning(
                            "crc error has been detected on MxFEs of %s", name
                        )
                    else:
                        logger.error(
                            "datalink between MxFE and FPGA of %s is not working", name
                        )
                        link_status = False
            else:
                if not all(box.link_status().values()):
                    if all(
                        box.link_status(
                            ignore_crc_error_of_mxfe=box.css.get_all_groups()
                        ).values()
                    ):
                        logger.warning(
                            "crc error has been detected on MxFEs of %s", name
                        )
                    else:
                        logger.error(
                            "datalink between MxFE and FPGA of %s is not working", name
                        )
                        link_status = False
            self._linkstatus[name] = link_status

    def reset_awg(self) -> None:
        """Stop and reinitialize all AWGs for all registered boxes."""
        for box, _ in self._boxes.values():
            # Some quel_ic_config type stubs do not expose this helper even though
            # runtime objects provide it in quelware 0.10.
            cast(Any, box).easy_stop_all(control_port_rfswitch=True)
            box.initialize_all_awgunits()

    def get_box(
        self,
        name: str,
    ) -> tuple[Quel1BoxWithRawWss, SequencerClient]:
        """Return the registered `(box, sequencer_client)` pair by name."""
        if name in self._boxes:
            box, sqc = self._boxes[name]
            return box, sqc
        raise ValueError(f"invalid name of box: '{name}'")

    def get_port_direction(self, box_name: str, port: Quel1PortType) -> str:
        """Return cached port direction (`in` or `out`) for a box port."""
        if (box_name, port) not in self._port_direction:
            box = self.get_box(box_name)[0]
            self._port_direction[(box_name, port)] = box.dump_port(port)["direction"]
        return self._port_direction[(box_name, port)]
