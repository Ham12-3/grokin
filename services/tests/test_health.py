"""Health endpoint: unit tests with fakes, plus one integration test with real services."""

import os
from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis

from api.main import API_PREFIX, app
from crew import __version__, health
from crew.config import Settings, get_settings
from crew.db import create_engine
from crew.health import check_db, check_redis


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def ping(self) -> bool:
        if self.fail:
            raise ConnectionError("redis down")
        return True


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app.state.settings = Settings(_env_file=None)
    app.state.engine = object()
    app.state.redis = FakeRedis()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_health_ok(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def db_ok(engine: Any, timeout_s: float) -> str:
        return "ok"

    monkeypatch.setattr(health, "check_db", db_ok)
    resp = await client.get(f"{API_PREFIX}/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "version": __version__, "db": "ok", "redis": "ok"}


async def test_health_degraded_when_db_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def db_down(engine: Any, timeout_s: float) -> str:
        return "error"

    monkeypatch.setattr(health, "check_db", db_down)
    body = (await client.get(f"{API_PREFIX}/health")).json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
    assert body["redis"] == "ok"


async def test_check_redis_reports_error() -> None:
    assert await check_redis(FakeRedis(fail=True), 1.0) == "error"


async def test_check_db_reports_error_when_unreachable() -> None:
    settings = Settings(
        _env_file=None, database_url="postgresql+asyncpg://crew:crew@127.0.0.1:1/crew"
    )
    engine = create_engine(settings)
    try:
        assert await check_db(engine, 2.0) == "error"
    finally:
        await engine.dispose()


@pytest.mark.integration
async def test_health_with_real_services() -> None:
    """Runs against the compose Postgres and Redis.

    Skipped locally when they are down. CI sets CREW_REQUIRE_SERVICES=1 so a
    missing service fails instead of skipping.
    """
    settings = get_settings()
    engine = create_engine(settings)
    redis = Redis.from_url(settings.redis_url)
    try:
        result = await health.get_health(engine, redis, 3.0)
    finally:
        await redis.aclose()
        await engine.dispose()
    if result.status != "ok" and not os.environ.get("CREW_REQUIRE_SERVICES"):
        pytest.skip("Postgres or Redis not reachable (run `make up`)")
    assert result.status == "ok"


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_the_desktop_app_may_use_every_method_the_api_has(
    client: AsyncClient, method: str
) -> None:
    """The app runs on another origin: the browser asks first (a pre-flight request)."""
    resp = await client.options(
        "/api/v1/bots/x/apps",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert resp.status_code == 200, method
    assert method in resp.headers["access-control-allow-methods"]
