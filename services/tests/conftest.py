"""Shared test setup.

Tests that touch the database run against a separate `<name>_test` Postgres database and
Redis database 15, so they never touch dev data. They are skipped when the services are
down, unless CREW_REQUIRE_SERVICES=1 (set in CI), which makes that a failure.
"""

import asyncio
import os
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path

import asyncpg
import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

_DEV_DB_URL = os.environ.get("DATABASE_URL", "postgresql+asyncpg://crew:crew@localhost:5432/crew")
_dev_url = make_url(_DEV_DB_URL)
_TEST_DB_NAME = f"{_dev_url.database}_test"
_TEST_DB_URL = _dev_url.set(database=_TEST_DB_NAME).render_as_string(hide_password=False)
_redis_base = os.environ.get("REDIS_URL", "redis://localhost:6379/0").rsplit("/", 1)[0]

# Fixed, fake values. Set before anything imports settings.
os.environ.update(
    {
        "CREW_ENV": "test",
        "DATABASE_URL": _TEST_DB_URL,
        "REDIS_URL": f"{_redis_base}/15",
        "JWT_SECRET": "test-only-jwt-secret-not-used-anywhere-real-0123456789",
        "GOOGLE_CLIENT_ID": "test-google-client-id",
        "GOOGLE_CLIENT_SECRET": "test-only-google-client-secret",
        "SMTP_URL": "",
        "API_BASE_URL": "http://localhost:8000",
        "DESKTOP_DEEP_LINK": "crew://auth",
        "WORKSPACES_DIR": tempfile.mkdtemp(prefix="crew-test-workspaces-"),
        "SEARCH_API_KEY": "",
        "LLM_PROVIDER": "anthropic",
        "COMPUTER_PROVIDER": "local",
    }
)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from api.main import create_app  # noqa: E402
from crew.computer.local_provider import LocalProvider  # noqa: E402
from crew.config import Settings, get_settings  # noqa: E402
from crew.tools import default_registry  # noqa: E402

SERVICES_DIR = Path(__file__).resolve().parents[1]


async def _create_test_database() -> None:
    conn = await asyncpg.connect(
        host=_dev_url.host,
        port=_dev_url.port or 5432,
        user=_dev_url.username,
        password=_dev_url.password,
        database=_dev_url.database,
        timeout=5,
    )
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _TEST_DB_NAME)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_TEST_DB_NAME}"')
    finally:
        await conn.close()


async def _check_redis() -> None:
    redis = Redis.from_url(os.environ["REDIS_URL"], socket_connect_timeout=3)
    try:
        await redis.ping()
    finally:
        await redis.aclose()


@pytest.fixture(scope="session")
def services_ready() -> bool:
    """Creates the test database and applies every migration. False when services are down."""
    get_settings.cache_clear()
    try:
        asyncio.run(_create_test_database())
        asyncio.run(_check_redis())
    except Exception as exc:
        if os.environ.get("CREW_REQUIRE_SERVICES"):
            raise RuntimeError("Postgres and Redis are required for this test run") from exc
        return False
    config = Config(str(SERVICES_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICES_DIR / "alembic"))
    config.attributes["skip_logging_config"] = True
    command.upgrade(config, "head")
    return True


class RecordingMailer:
    """Stands in for email: keeps the links so tests can click them."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_magic_link(self, email: str, link: str) -> None:
        self.sent.append((email, link))


@dataclass
class GoogleStub:
    """A fake Google: answers the token and userinfo calls the API makes."""

    userinfo: dict[str, object] = field(
        default_factory=lambda: {
            "email": "ada@example.com",
            "email_verified": True,
            "name": "Ada Lovelace",
            "picture": "https://example.com/ada.png",
        }
    )
    token_status: int = 200
    requests: list[httpx.Request] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path.endswith("/token"):
            return httpx.Response(self.token_status, json={"access_token": "fake-google-token"})
        return httpx.Response(200, json=self.userinfo)


class RecordingQueue:
    """Stands in for ARQ: remembers the jobs so tests can run them by hand."""

    def __init__(self) -> None:
        self.jobs: list[tuple[str, tuple[object, ...]]] = []

    async def enqueue_job(self, function: str, *args: object) -> object:
        self.jobs.append((function, args))
        return None


@dataclass
class Ctx:
    app: FastAPI
    client: AsyncClient
    settings: Settings
    engine: AsyncEngine
    redis: Redis
    mailer: RecordingMailer
    google: GoogleStub
    queue: RecordingQueue
    session_factory: async_sessionmaker[AsyncSession]


@pytest.fixture
async def ctx(services_ready: bool) -> AsyncIterator[Ctx]:
    if not services_ready:
        pytest.skip("Postgres or Redis not reachable (run `make up`)")
    settings = get_settings()
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    await redis.flushdb()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE users, refresh_tokens, audit_log, bots, chats, chat_members, "
                "messages, runs, tool_calls, usage_daily, computers, approvals, connector_log, memories, "
                "skills "
                "CASCADE"
            )
        )

    google = GoogleStub()
    http = httpx.AsyncClient(transport=httpx.MockTransport(google.handler))
    mailer = RecordingMailer()

    app = create_app()
    app.state.settings = settings
    app.state.engine = engine
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    queue = RecordingQueue()
    app.state.session_factory = session_factory
    app.state.queue = queue
    app.state.provider = LocalProvider(settings)
    app.state.registry = default_registry()
    app.state.redis = redis
    app.state.http = http
    app.state.mailer = mailer

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield Ctx(app, client, settings, engine, redis, mailer, google, queue, session_factory)

    await http.aclose()
    await redis.flushdb()
    await redis.aclose()
    await engine.dispose()


@pytest.fixture
async def live_ws(ctx: Ctx) -> AsyncIterator[str]:
    """Serves the app on a real local port for WebSocket tests. Yields the ws:// URL."""
    config = uvicorn.Config(ctx.app, host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"ws://127.0.0.1:{port}/api/v1/ws"
    server.should_exit = True
    await task
