"""WebSocket: auth on connect, ownership checks on subscribe, live events."""

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.typing import Subprotocol

from crew import events
from crew.auth.tokens import JWT_ALGORITHM
from crew.llm.fake import FakeLLM
from tests.conftest import Ctx
from tests.helpers import API, create_bot, run_worker, send, sign_in


def _protocols(token: str | None) -> list[Subprotocol]:
    protocols = [Subprotocol("crew.v1")]
    if token is not None:
        protocols.append(Subprotocol(f"bearer.{token}"))
    return protocols


def _token(headers: dict[str, str]) -> str:
    return headers["Authorization"].removeprefix("Bearer ")


async def _next(socket: ClientConnection, event_type: str) -> dict[str, Any]:
    """Reads until an event of this type arrives."""
    async with asyncio.timeout(5):
        while True:
            event: dict[str, Any] = json.loads(await socket.recv())
            if event["type"] == event_type:
                return event


async def _command(socket: ClientConnection, **message: str) -> None:
    await socket.send(json.dumps(message))


@pytest.mark.parametrize("token", [None, "garbage", ""])
async def test_connection_without_a_valid_token_is_refused(
    ctx: Ctx, live_ws: str, token: str | None
) -> None:
    with pytest.raises(InvalidStatus) as refused:
        async with connect(live_ws, subprotocols=_protocols(token)):
            pass
    assert refused.value.response.status_code == 403


async def test_expired_token_is_refused(ctx: Ctx, live_ws: str) -> None:
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "exp": datetime.now(UTC) - timedelta(minutes=1),
            "typ": "access",
        },
        ctx.settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    with pytest.raises(InvalidStatus):
        async with connect(live_ws, subprotocols=_protocols(expired)):
            pass


async def test_token_in_the_url_is_not_accepted(ctx: Ctx, live_ws: str) -> None:
    me = await sign_in(ctx, "a@example.com")
    with pytest.raises(InvalidStatus):
        async with connect(f"{live_ws}?token={_token(me)}", subprotocols=_protocols(None)):
            pass


async def test_ping_pong_and_bad_messages(ctx: Ctx, live_ws: str) -> None:
    me = await sign_in(ctx, "a@example.com")
    async with connect(live_ws, subprotocols=_protocols(_token(me))) as socket:
        assert socket.subprotocol == "crew.v1"
        await _command(socket, type="ping")
        assert (await _next(socket, "pong"))["type"] == "pong"
        await socket.send("not json")
        assert (await _next(socket, "error"))["code"] == "invalid_message"
        await _command(socket, type="subscribe", chat_id="not-a-uuid")
        assert (await _next(socket, "error"))["code"] == "invalid_message"


async def test_cannot_subscribe_to_another_users_chat(ctx: Ctx, live_ws: str) -> None:
    alice = await sign_in(ctx, "alice@example.com")
    bob = await sign_in(ctx, "bob@example.com")
    alice_chat = (await create_bot(ctx, alice))["direct_chat_id"]
    bob_chat = (await create_bot(ctx, bob))["direct_chat_id"]

    async with connect(live_ws, subprotocols=_protocols(_token(bob))) as socket:
        await _command(socket, type="subscribe", chat_id=alice_chat)
        refused = await _next(socket, "error")
        assert refused["code"] == "chat_not_found" and refused["chat_id"] == alice_chat
        await _command(socket, type="subscribe", chat_id=str(uuid.uuid4()))
        assert (await _next(socket, "error"))["code"] == "chat_not_found"

        await _command(socket, type="subscribe", chat_id=bob_chat)
        assert (await _next(socket, "subscribed"))["chat_id"] == bob_chat

        # Events on Alice's chat never reach Bob; events on his own chat do.
        await events.publish(ctx.redis, events.chat_channel(alice_chat), "secret", {"x": 1})
        await events.publish(ctx.redis, events.chat_channel(bob_chat), "mine", {"x": 2})
        received = json.loads(await asyncio.wait_for(socket.recv(), 5))
        assert received["type"] == "mine"


async def test_unsubscribe_stops_events(ctx: Ctx, live_ws: str) -> None:
    me = await sign_in(ctx, "a@example.com")
    chat_id = (await create_bot(ctx, me))["direct_chat_id"]
    async with connect(live_ws, subprotocols=_protocols(_token(me))) as socket:
        await _command(socket, type="subscribe", chat_id=chat_id)
        await _next(socket, "subscribed")
        await _command(socket, type="unsubscribe", chat_id=chat_id)
        await _next(socket, "unsubscribed")
        await events.publish(ctx.redis, events.chat_channel(chat_id), "after", {})
        await _command(socket, type="ping")
        assert json.loads(await asyncio.wait_for(socket.recv(), 5))["type"] == "pong"


async def test_reply_streams_to_the_socket_end_to_end(ctx: Ctx, live_ws: str) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    chat_id = bot["direct_chat_id"]

    async with connect(live_ws, subprotocols=_protocols(_token(me))) as socket:
        await _command(socket, type="subscribe", chat_id=chat_id)
        await _next(socket, "subscribed")

        sent = await send(ctx, me, chat_id, "hello")
        assert (await _next(socket, "message.created"))["message"]["content"] == "hello"
        assert (await _next(socket, "run.status"))["status"] == "queued"

        await run_worker(ctx, sent["run_id"], FakeLLM(["Hi ", "there"]))

        seen: list[dict[str, Any]] = []
        async with asyncio.timeout(5):
            while not (
                seen and seen[-1]["type"] == "run.status" and seen[-1]["status"] == "completed"
            ):
                seen.append(json.loads(await socket.recv()))
        text = "".join(e["text"] for e in seen if e["type"] == "message.delta")
        assert text == "Hi there"
        assert [e["type"] for e in seen if e["type"].startswith("message.")] == [
            "message.created",
            "message.delta",
            "message.delta",
            "message.completed",
        ]


async def test_connection_closes_when_the_token_expires(ctx: Ctx, live_ws: str) -> None:
    me = await sign_in(ctx, "a@example.com")
    user_id = (await ctx.client.get(f"{API}/me", headers=me)).json()["id"]
    short = jwt.encode(
        {"sub": user_id, "exp": datetime.now(UTC) + timedelta(seconds=2), "typ": "access"},
        ctx.settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    async with connect(live_ws, subprotocols=_protocols(short)) as socket:
        with pytest.raises(ConnectionClosed) as closed:
            await asyncio.wait_for(socket.recv(), 6)
    assert closed.value.rcvd is not None and closed.value.rcvd.code == 4401
