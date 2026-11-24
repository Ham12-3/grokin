"""Realtime events over Redis pub/sub.

Two kinds of channel: `chat:{chat_id}` for message events in one chat, and
`user:{user_id}` for things the whole app cares about (run status, for the status dots).
The API WebSocket forwards them to the desktop app. Payloads are safe text: no secrets.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from redis.asyncio import Redis


def chat_channel(chat_id: uuid.UUID | str) -> str:
    return f"chat:{chat_id}"


def user_channel(user_id: uuid.UUID | str) -> str:
    return f"user:{user_id}"


def encode(event_type: str, payload: dict[str, Any]) -> str:
    return json.dumps({"type": event_type, "ts": datetime.now(UTC).isoformat(), **payload})


async def publish(redis: Redis, channel: str, event_type: str, payload: dict[str, Any]) -> None:
    await redis.publish(channel, encode(event_type, payload))
