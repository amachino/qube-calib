"""Clock-master and sequencer client compatibility wrappers."""

from __future__ import annotations

import logging
from contextlib import suppress
from dataclasses import dataclass, field
from threading import RLock

from quel_ic_config import Quel1Box, QuelClockMasterV1

_BOX_BY_SSS_IPADDR: dict[str, Quel1Box] = {}
logger = logging.getLogger(__name__)
_CLOCKMASTER_BOXES_ATTR = "_boxes"


@dataclass
class _SharedClockMaster:
    """Shared clock-master session and synchronization primitives."""

    master: QuelClockMasterV1
    ref_count: int = 0
    lock: RLock = field(default_factory=RLock)


_SHARED_CLOCKMASTERS: dict[str, _SharedClockMaster] = {}
_SHARED_CLOCKMASTERS_LOCK = RLock()


def _acquire_shared_clockmaster(ipaddr: str) -> _SharedClockMaster:
    """Acquire or create one shared clock-master session for the given IP."""
    with _SHARED_CLOCKMASTERS_LOCK:
        shared = _SHARED_CLOCKMASTERS.get(ipaddr)
        if shared is None:
            shared = _SharedClockMaster(
                master=QuelClockMasterV1(ipaddr=ipaddr, boxes=[])
            )
            _SHARED_CLOCKMASTERS[ipaddr] = shared
        shared.ref_count += 1
        return shared


def _release_shared_clockmaster(ipaddr: str, shared: _SharedClockMaster) -> None:
    """Release one shared clock-master reference and terminate at ref-count zero."""
    with _SHARED_CLOCKMASTERS_LOCK:
        current = _SHARED_CLOCKMASTERS.get(ipaddr)
        if current is None or current is not shared:
            return
        shared.ref_count -= 1
        if shared.ref_count > 0:
            return
        with shared.lock:
            shared.master.terminate()
        del _SHARED_CLOCKMASTERS[ipaddr]


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
        self._shared_master = _acquire_shared_clockmaster(self._master_ipaddr)
        self._closed = False

    def __del__(self) -> None:
        """Terminate the cached clock-master session on object finalization."""
        with suppress(Exception):
            self.close()

    @property
    def _master(self) -> QuelClockMasterV1:
        """Return the shared clock-master session."""
        return self._shared_master.master

    def close(self) -> None:
        """Terminate the cached clock-master session."""
        if self._closed:
            return
        _release_shared_clockmaster(self._master_ipaddr, self._shared_master)
        self._closed = True

    def _set_master_boxes(self, boxes: list[Quel1Box]) -> None:
        """Update target boxes on the cached clock-master session."""
        # `QuelClockMasterV1` does not expose a public setter for sync targets.
        setattr(self._master, _CLOCKMASTER_BOXES_ATTR, set(boxes))

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
        with self._shared_master.lock:
            self._set_master_boxes(boxes)
            self._master.sync_boxes()

    def read_clock(self) -> tuple[bool, int]:
        """
        Read current counter value from the clock master.

        Returns
        -------
        tuple[bool, int]
            `(success, current_counter)`.
        """
        with self._shared_master.lock:
            counter = int(self._master.get_current_timecounter())
        return True, counter

    def reset(self) -> bool:
        """Reset the clock master when supported by backend implementation."""
        logger.warning(
            "Clock master reset is not supported by the current quelware "
            "implementation."
        )
        return False


__all__ = [
    "QuBEMasterClient",
    "SequencerClient",
    "register_box",
]
