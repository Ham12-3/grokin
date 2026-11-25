"""Pipes a client's WebSocket to a display's live screen. The API checks who is asking first."""

import asyncio
import contextlib
from typing import Protocol

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, WebSocketException
from websockets.typing import Subprotocol

CLOSE_UNAUTHORIZED = 4401
CLOSE_UNAVAILABLE = 4503


class BinarySocket(Protocol):
    async def receive_bytes(self) -> bytes: ...
    async def send_bytes(self, data: bytes) -> None: ...
    async def close(self, code: int = 1000, reason: str | None = None) -> None: ...


async def proxy(client: BinarySocket, upstream_url: str, *, expires_in: float) -> None:
    """Runs until either side leaves or the client's access token expires."""
    try:
        upstream = await connect(
            upstream_url, subprotocols=[Subprotocol("binary")], max_size=None, open_timeout=10
        )
    except (OSError, WebSocketException, TimeoutError):
        with contextlib.suppress(Exception):
            await client.close(CLOSE_UNAVAILABLE, "screen not available")
        return

    async def to_client() -> None:
        with contextlib.suppress(ConnectionClosed):
            async for data in upstream:
                await client.send_bytes(data if isinstance(data, bytes) else data.encode())

    async def to_upstream() -> None:
        with contextlib.suppress(ConnectionClosed):
            while True:
                await upstream.send(await client.receive_bytes())

    tasks = [asyncio.create_task(to_client()), asyncio.create_task(to_upstream())]
    try:
        done, _ = await asyncio.wait(
            tasks, timeout=max(expires_in, 0), return_when=asyncio.FIRST_COMPLETED
        )
        if not done:
            with contextlib.suppress(Exception):
                await client.close(CLOSE_UNAUTHORIZED, "token expired")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with contextlib.suppress(Exception):
            await upstream.close()
        with contextlib.suppress(Exception):
            await client.close()
