"""Shared helpers for API tests."""

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

from crew.agent.loop import run_agent
from crew.auth.tokens import new_token, pkce_challenge
from crew.config import Settings
from crew.llm.base import LLM, LLMError
from crew.tools import default_registry
from crew.tools.registry import ToolRegistry
from tests.conftest import Ctx

API = "/api/v1"
PUBLIC_IP = "93.184.216.34"

Handler = Callable[[httpx.Request], httpx.Response]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def sign_in(ctx: Ctx, email: str) -> dict[str, str]:
    """Signs in through the magic-link flow and returns auth headers."""
    verifier = new_token(48)
    start = await ctx.client.post(
        f"{API}/auth/email/start",
        json={"email": email, "code_challenge": pkce_challenge(verifier)},
    )
    assert start.status_code == 200, start.text
    link = ctx.mailer.sent[-1][1]
    page = await ctx.client.get(urlsplit(link).path + "?" + urlsplit(link).query)
    match = re.search(r'href="crew://auth\?code=([A-Za-z0-9_-]+)"', page.text)
    assert match, page.text
    resp = await ctx.client.post(
        f"{API}/auth/exchange", json={"code": match.group(1), "code_verifier": verifier}
    )
    assert resp.status_code == 200, resp.text
    return bearer(resp.json()["access_token"])


async def create_bot(
    ctx: Ctx, headers: dict[str, str], name: str = "Inbox Bot", **fields: str
) -> dict[str, Any]:
    resp = await ctx.client.post(
        f"{API}/bots",
        headers=headers,
        json={
            "name": name,
            "avatar": "📬",
            "job": "Sorts my inbox",
            "instructions": "Be brief.",
            **fields,
        },
    )
    assert resp.status_code == 201, resp.text
    bot: dict[str, Any] = resp.json()
    return bot


async def send(ctx: Ctx, headers: dict[str, str], chat_id: str, content: str) -> dict[str, Any]:
    resp = await ctx.client.post(
        f"{API}/chats/{chat_id}/messages", headers=headers, json={"content": content}
    )
    assert resp.status_code == 202, resp.text
    body: dict[str, Any] = resp.json()
    return body


async def public_resolver(host: str, port: int) -> list[str]:
    """Pretends every hostname is a public site, so tests never touch real DNS."""
    return [PUBLIC_IP]


def no_web(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected web request: {request.url}")


async def run_worker(
    ctx: Ctx,
    run_id: str,
    llm: LLM | None,
    llm_error: LLMError | None = None,
    *,
    registry: ToolRegistry | None = None,
    web: Handler = no_web,
    settings: Settings | None = None,
) -> str:
    """Runs the queued job the way the ARQ worker would. `web` answers outgoing requests."""
    async with httpx.AsyncClient(transport=httpx.MockTransport(web)) as http:
        return await run_agent(
            uuid.UUID(run_id),
            session_factory=ctx.session_factory,
            redis=ctx.redis,
            settings=settings or ctx.settings,
            llm=llm,
            registry=registry or default_registry(public_resolver),
            http=http,
            llm_error=llm_error,
        )


class Listener:
    """Collects the events published on some Redis channels."""

    def __init__(self, ctx: Ctx, *channels: str) -> None:
        self._pubsub = ctx.redis.pubsub()
        self._channels = channels
        self.events: list[dict[str, Any]] = []

    async def __aenter__(self) -> "Listener":
        await self._pubsub.subscribe(*self._channels)
        return self

    async def __aexit__(self, *_: object) -> None:
        await asyncio.sleep(0.05)
        while True:
            item = await self._pubsub.get_message(timeout=0.1)
            if item is None:
                break
            if item["type"] == "message":
                self.events.append(json.loads(item["data"]))
        await self._pubsub.aclose()  # type: ignore[no-untyped-call]

    def of(self, event_type: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["type"] == event_type]
