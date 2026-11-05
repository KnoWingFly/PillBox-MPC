"""Stock counts this process last committed from a heartbeat, per device.

A heartbeat whose counts equal the last committed ones skips the
device_stocks upsert (one remote round trip per heartbeat). Every other
writer of device_stocks calls forget(); STOCK_CACHE_REWRITE_SECONDS bounds how long a
change made outside this process (another worker, manual SQL) can stay
uncorrected. Process memory only, like connection_manager.py.
"""

import time
from uuid import UUID

from app.core.config import get_settings


Counts = tuple[tuple[int, int], ...]
_written: dict[UUID, tuple[Counts, float]] = {}


def is_current(device_id: UUID, counts: Counts) -> bool:
    entry = _written.get(device_id)
    rewrite_after = get_settings().stock_cache_rewrite_seconds
    return entry is not None and entry[0] == counts and time.monotonic() - entry[1] < rewrite_after


def remember(device_id: UUID, counts: Counts) -> None:
    """Call only after the transaction that wrote `counts` committed."""
    _written[device_id] = (counts, time.monotonic())


def forget(device_id: UUID) -> None:
    _written.pop(device_id, None)
