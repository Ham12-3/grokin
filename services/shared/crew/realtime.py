"""One WebSocket connection: forwards Redis events to the desktop app.

The connection always listens on the user's own channel. Chat channels are added with
`subscribe`, after checking that the user owns the chat.
"""

import asyncio
import contextlib
import json
import uuid
from typing import Protocol

import structlog
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew import events
from crew.chats.service import user_owns_chat

log = structlog.get_logger(__name__)

CLOSE_UNAUTHORIZED = 4401
MAX_CLIENT_MESSAGE_CHARS = 1000


class Socket(Protocol):
    async def receive_text(self) -> str: ...
    async def send_text(self, data: str) -> None: ...
    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


class Connection:
    def __init__(
        self,
        socket: Socket,
        redis: Redis,
        session_factory: async_sessionmaker[AsyncSession],
        user_id: uuid.UUID,
        *,
        max_subscriptions: int,
    ) -> None:
        self._socket = socket
        self._pubsub = redis.pubsub()
        self._session_factory = session_factory
        self._user_id = user_id
        self._max_subscriptions = max_subscriptions
        self._chats: set[uuid.UUID] = set()
        self._send_lock = asyncio.Lock()

    async def _send(self, event_type: str, **payload: object) -> None:
        async with self._send_lock:
            await self._socket.send_text(events.encode(event_type, payload))

    async def _forward(self) -> None:
        async for item in self._pubsub.listen():
            if item["type"] == "message":
                async with self._send_lock:
                    await self._socket.send_text(item["data"])

    async def _subscribe(self, chat_id: uuid.UUID) -> None:
        if chat_id in self._chats:
            await self._send("subscribed", chat_id=str(chat_id))
            return
        if len(self._chats) >= self._max_subscriptions:
            await self._send("error", code="too_many_subscriptions", chat_id=str(chat_id))
            return
        async with self._session_factory() as session:
            owned = await user_owns_chat(session, self._user_id, chat_id)
        if not owned:
            # Same answer for "not yours" and "does not exist".
            await self._send("error", code="chat_not_found", chat_id=str(chat_id))
            return
        await self._pubsub.subscribe(events.chat_channel(chat_id))
        self._chats.add(chat_id)
        await self._send("subscribed", chat_id=str(chat_id))

    async def _unsubscribe(self, chat_id: uuid.UUID) -> None:
        if chat_id in self._chats:
            await self._pubsub.unsubscribe(events.chat_channel(chat_id))
            self._chats.discard(chat_id)
        await self._send("unsubscribed", chat_id=str(chat_id))

    async def _handle(self, raw: str) -> None:
        if len(raw) > MAX_CLIENT_MESSAGE_CHARS:
            await self._send("error", code="invalid_message")
            return
        try:
            message = json.loads(raw)
            kind = message["type"]
            if kind == "ping":
                await self._send("pong")
                return
            chat_id = uuid.UUID(message["chat_id"])
        except (ValueError, KeyError, TypeError):
            await self._send("error", code="invalid_message")
            return
        if kind == "subscribe":
            await self._subscribe(chat_id)
        elif kind == "unsubscribe":
            await self._unsubscribe(chat_id)
        else:
            await self._send("error", code="invalid_message")

    async def _receive(self) -> None:
        while True:
            await self._handle(await self._socket.receive_text())

    async def run(self, *, expires_in: float) -> None:
        """Serves until the client leaves or the access token expires."""
        await self._pubsub.subscribe(events.user_channel(self._user_id))
        tasks = [asyncio.create_task(self._forward()), asyncio.create_task(self._receive())]
        try:
            done, _ = await asyncio.wait(
                tasks, timeout=max(expires_in, 0), return_when=asyncio.FIRST_COMPLETED
            )
            if not done:
                # The client reconnects with a fresh token.
                with contextlib.suppress(Exception):
                    await self._socket.close(CLOSE_UNAUTHORIZED, "token expired")
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            with contextlib.suppress(Exception):
                await self._pubsub.aclose()  # type: ignore[no-untyped-call]
