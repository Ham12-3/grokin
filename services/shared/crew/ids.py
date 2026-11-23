"""UUID v7 ids (time-ordered). Python 3.12 has no built-in uuid7."""

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """48-bit Unix milliseconds, then version and variant bits, then random bits (RFC 9562)."""
    ms = time.time_ns() // 1_000_000
    value = ((ms & ((1 << 48) - 1)) << 80) | int.from_bytes(os.urandom(10), "big")
    value = (value & ~(0xF << 76)) | (0x7 << 76)  # version 7
    value = (value & ~(0x3 << 62)) | (0x2 << 62)  # RFC variant
    return uuid.UUID(int=value)
