"""Shared helpers for API tests."""

import asyncio
import json
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from crew.agent.loop import run_agent
from crew.auth.tokens import new_token, pkce_challenge
from crew.computer.local_provider import LocalProvider
from crew.computer.provider import (
    ComputerError,
    ComputerHandle,
    ComputerProvider,
    ComputerState,
    ExecResult,
)
from crew.config import Settings
from crew.llm.base import LLM, LLMError
from crew.tools import default_registry
from crew.tools.registry import ToolContext, ToolRegistry
from tests.conftest import Ctx

API = "/api/v1"
PUBLIC_IP = "93.184.216.34"

Handler = Callable[[httpx.Request], httpx.Response]

SNAPSHOT: dict[str, Any] = {
    "title": "Example",
    "url": "https://example.com/",
    "text": "Welcome to Example.",
    "elements": [
        {"id": 1, "tag": "a", "type": "", "label": "More information"},
        {"id": 2, "tag": "input", "type": "text", "label": "Search"},
        {"id": 3, "tag": "button", "type": "submit", "label": "Send message"},
    ],
}


class FakeProvider(LocalProvider):
    """Files on disk like LocalProvider, plus a scripted terminal, browser and screen."""

    name = "fake"

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.running: set[uuid.UUID] = set()
        self.ensured = 0
        self.stopped = 0
        self.commands: list[str] = []
        self.displays: list[int] = []
        self.browser_calls: list[tuple[int, str, dict[str, Any]]] = []
        self.snapshot: dict[str, Any] = SNAPSHOT
        self.exec_result = ExecResult(0, "hello\n", "", False)
        self.fail_start: str | None = None
        self.vnc: str | None = None

    async def ensure(self, user_id: uuid.UUID) -> ComputerHandle:
        if self.fail_start is not None:
            raise ComputerError(self.fail_start)
        self.ensured += 1
        self.running.add(user_id)
        return ComputerHandle(user_id, "fake://", "test-only-token")

    async def stop(self, user_id: uuid.UUID) -> None:
        self.stopped += 1
        self.running.discard(user_id)

    async def state(self, user_id: uuid.UUID) -> ComputerState:
        return "running" if user_id in self.running else "stopped"

    async def exec(
        self, handle: ComputerHandle, cmd: str, timeout_s: float, display: int | None = None
    ) -> ExecResult:
        self.commands.append(cmd)
        return self.exec_result

    async def start_display(self, handle: ComputerHandle, display: int) -> None:
        self.displays.append(display)

    async def browser(
        self, handle: ComputerHandle, display: int, action: str, **args: Any
    ) -> dict[str, Any]:
        self.browser_calls.append((display, action, args))
        if action == "screenshot":
            return {"path": "/workspace/outputs/screenshots/screen-1.png", "size": 10}
        return self.snapshot

    def vnc_url(self, handle: ComputerHandle, display: int) -> str:
        if self.vnc is None:
            raise ComputerError("no screen in this test")
        return f"{self.vnc}/{display}"


class StubComputer:
    """Stands in for RunComputer in tool tests that have no database."""

    def __init__(self, provider: ComputerProvider, user_id: uuid.UUID) -> None:
        self.provider = provider
        self.element_labels: dict[int, str] = {}
        self.page_url = ""
        self.page_text = ""
        self._user_id = user_id
        self.displays_taken = 0
        self.started = False

    async def handle(self) -> ComputerHandle:
        self.started = True
        return await self.provider.ensure(self._user_id)

    async def display(self) -> int:
        self.displays_taken += 1
        return 1


async def _no_takeover(reason: str) -> None:
    raise AssertionError("takeover not expected in this test")


def tool_context(
    http: httpx.AsyncClient,
    workspace: Path,
    provider: ComputerProvider | None = None,
    **overrides: object,
) -> ToolContext:
    """A ToolContext for tool tests: local files under `workspace`, no database."""
    settings = Settings(_env_file=None, workspaces_dir=str(workspace), **overrides)  # type: ignore[arg-type]
    user_id = uuid.uuid4()
    return ToolContext(
        user_id=user_id,
        run_id=uuid.uuid4(),
        settings=settings,
        http=http,
        computer=StubComputer(provider or LocalProvider(settings), user_id),
        takeover=_no_takeover,
    )


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
    provider: ComputerProvider | None = None,
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
            provider=provider or ctx.app.state.provider,
            llm_error=llm_error,
            queue=ctx.queue,
            vault=ctx.app.state.vault,
            connectors=ctx.app.state.connectors,
            mcp_opener=ctx.app.state.mcp_opener,
            storage=ctx.app.state.storage,
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


async def connect_app(
    ctx: Ctx, headers: dict[str, str], bot: dict[str, Any], kind: str = "gmail"
) -> dict[str, Any]:
    """Connects an app (the stand-in backend connects at once) and lets the Bot use it."""
    started = await ctx.client.post(f"{API}/connectors/{kind}/connect", headers=headers)
    assert started.status_code == 200, started.text
    connector: dict[str, Any] = started.json()["connector"]
    current = (await ctx.client.get(f"{API}/bots/{bot['id']}/apps", headers=headers)).json()
    allowed = await ctx.client.put(
        f"{API}/bots/{bot['id']}/apps",
        headers=headers,
        json={"connector_ids": [*current["connector_ids"], connector["id"]]},
    )
    assert allowed.status_code == 200, allowed.text
    return connector
