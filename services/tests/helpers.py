"""Shared helpers for API tests."""

import re
import uuid
from typing import Any
from urllib.parse import urlsplit

from crew.auth.tokens import new_token, pkce_challenge
from crew.llm.base import LLM, LLMError
from crew.runs.agent import run_agent
from tests.conftest import Ctx

API = "/api/v1"


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


async def create_bot(ctx: Ctx, headers: dict[str, str], name: str = "Inbox Bot") -> dict[str, Any]:
    resp = await ctx.client.post(
        f"{API}/bots",
        headers=headers,
        json={"name": name, "avatar": "📬", "job": "Sorts my inbox", "instructions": "Be brief."},
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


async def run_worker(
    ctx: Ctx, run_id: str, llm: LLM | None, llm_error: LLMError | None = None
) -> str:
    """Runs the queued job the way the ARQ worker would."""
    return await run_agent(
        uuid.UUID(run_id),
        session_factory=ctx.session_factory,
        redis=ctx.redis,
        settings=ctx.settings,
        llm=llm,
        llm_error=llm_error,
    )
