"""Clock-master and sequencer client compatibility wrappers."""

from __future__ import annotations

import logging

from quel_ic_config import Quel1Box, QuelClockMasterV1

_BOX_BY_SSS_IPADDR: dict[str, Quel1Box] = {}
logger = logging.getLogger(__name__)


def register_box(box: Quel1Box) -> None:
    """Register a box instance for SSS-IP based clock access."""
    _BOX_BY_SSS_IPADDR[str(box.wss.ipaddr_sss)] = box


class SequencerClient:
    """Sequencer clock reader compatible with legacy qube-calib API."""

    def __init__(
        self,
        target_ipaddr: str,
        *,
        box: Quel1Box | None = None,
    ) -> None:
        self._target_ipaddr = str(target_ipaddr)
        self._box = box

    def read_clock(self) -> tuple[bool, int, int]:
        """
        Read current and SYSREF counters from the associated box.

        Returns
        -------
        tuple[bool, int, int]
            `(success, current_counter, latest_sysref_counter)`.
        """
        box = self._box or _BOX_BY_SSS_IPADDR.get(self._target_ipaddr)
        if box is None:
            raise RuntimeError(
                f"box for SSS IP {self._target_ipaddr} is not registered"
            )
        return (
            True,
            int(box.get_current_timecounter()),
            int(box.get_latest_sysref_timecounter()),
        )


class QuBEMasterClient:
    """Clock-master client compatible with legacy qube-calib API."""

    def __init__(
        self,
        master_ipaddr: str | None = None,
        *,
        ipaddr: str | None = None,
    ) -> None:
        resolved = master_ipaddr if master_ipaddr is not None else ipaddr
        if resolved is None:
            raise ValueError("master_ipaddr or ipaddr must be provided")
        self._master_ipaddr = str(resolved)

    def kick_clock_synch(self, box_sss_ipaddrs: list[str]) -> None:
        """
        Trigger clock synchronization across registered boxes.

        Parameters
        ----------
        box_sss_ipaddrs : list[str]
            SSS addresses of boxes to synchronize.
        """
        boxes = []
        for ipaddr in box_sss_ipaddrs:
            box = _BOX_BY_SSS_IPADDR.get(str(ipaddr))
            if box is None:
                raise RuntimeError(f"box for SSS IP {ipaddr} is not registered")
            boxes.append(box)
        master = QuelClockMasterV1(ipaddr=self._master_ipaddr, boxes=boxes)
        try:
            master.sync_boxes()
        finally:
            master.terminate()

    def read_clock(self) -> tuple[bool, int]:
        """
        Read current counter value from the clock master.

        Returns
        -------
        tuple[bool, int]
            `(success, current_counter)`.
        """
        master = QuelClockMasterV1(ipaddr=self._master_ipaddr, boxes=[])
        try:
            counter = int(master.get_current_timecounter())
        finally:
            master.terminate()
        return True, counter

    def reset(self) -> bool:
        """Reset the clock master when supported by backend implementation."""
        logger.warning(
            "Clock master reset is not supported by the current quelware "
            "implementation."
        )
        return False
