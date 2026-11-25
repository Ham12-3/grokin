"""WebSocket endpoint. Logic lives in `crew.realtime`.

The access token travels in the `Sec-WebSocket-Protocol` header, not the URL, so it never
lands in access logs. The client offers two subprotocols: `crew.v1` and `bearer.<token>`.
"""

import time
import uuid

from fastapi import APIRouter, WebSocket

from crew.auth.tokens import decode_access_claims
from crew.errors import AppError
from crew.models import User
from crew.realtime import CLOSE_UNAUTHORIZED, Connection

router = APIRouter()

PROTOCOL = "crew.v1"
TOKEN_PREFIX = "bearer."  # noqa: S105


async def authenticate(websocket: WebSocket) -> tuple[uuid.UUID, float] | None:
    """Reads the bearer token from the offered subprotocols.

    Returns the user id and the token's expiry time, or None when the caller must be refused.
    """
    state = websocket.app.state
    offered: list[str] = websocket.scope.get("subprotocols", [])
    token = next((p[len(TOKEN_PREFIX) :] for p in offered if p.startswith(TOKEN_PREFIX)), None)
    if token is None:
        return None
    try:
        user_id, expires_at = decode_access_claims(token, state.settings)
    except AppError:
        return None
    async with state.session_factory() as session:
        if await session.get(User, user_id) is None:
            return None
    return user_id, expires_at


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    state = websocket.app.state
    offered: list[str] = websocket.scope.get("subprotocols", [])
    identity = await authenticate(websocket) if PROTOCOL in offered else None
    if identity is None:
        # Closing before accepting makes the handshake fail (HTTP 403).
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    user_id, expires_at = identity

    await websocket.accept(subprotocol=PROTOCOL)
    connection = Connection(
        websocket,
        state.redis,
        state.session_factory,
        user_id,
        max_subscriptions=state.settings.ws_max_subscriptions,
    )
    await connection.run(expires_in=expires_at - time.time())
