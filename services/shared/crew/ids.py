"""UUID v7 ids (time-ordered). Python 3.12 has no built-in uuid7.

Rows are listed in id order (messages, tool calls, runs), so two ids made in the same
millisecond must still come out in the order they were made. The 12 bits after the
millisecond hold the sub-millisecond time (RFC 9562, method 3), and within one process an
id is never smaller than the one before it.
"""

import os
import threading
import time
import uuid

_lock = threading.Lock()
_last = 0  # the top 60 time bits of the newest id: 48 of milliseconds, 12 of fraction


def uuid7() -> uuid.UUID:
    """48-bit Unix milliseconds, 12-bit sub-millisecond time, then 62 random bits."""
    global _last
    ms, fraction = divmod(time.time_ns(), 1_000_000)
    stamp = ((ms & ((1 << 48) - 1)) << 12) | (fraction * 4096 // 1_000_000)
    with _lock:
        if stamp <= _last:
            stamp = _last + 1  # same instant (or the clock stepped back): keep the order
        _last = stamp
    value = (stamp >> 12) << 80  # milliseconds
    value |= 0x7 << 76  # version 7
    value |= (stamp & 0xFFF) << 64  # sub-millisecond time
    value |= 0x2 << 62  # RFC variant
    value |= int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    return uuid.UUID(int=value)
