"""Real health checks for Postgres and Redis."""

import asyncio
from typing import Protocol

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from crew import __version__
from crew.schemas.health import CheckStatus, HealthResponse

log = structlog.get_logger(__name__)


class Pingable(Protocol):
    async def ping(self) -> object: ...


async def check_db(engine: AsyncEngine, timeout_s: float) -> CheckStatus:
    async def ping() -> None:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    try:
        await asyncio.wait_for(ping(), timeout_s)
    except Exception as exc:
        log.warning("health.db_failed", error=type(exc).__name__)
        return "error"
    return "ok"


async def check_redis(redis: Pingable, timeout_s: float) -> CheckStatus:
    try:
        await asyncio.wait_for(redis.ping(), timeout_s)
    except Exception as exc:
        log.warning("health.redis_failed", error=type(exc).__name__)
        return "error"
    return "ok"


async def get_health(engine: AsyncEngine, redis: Pingable, timeout_s: float) -> HealthResponse:
    db, rd = await asyncio.gather(check_db(engine, timeout_s), check_redis(redis, timeout_s))
    ok = db == "ok" and rd == "ok"
    return HealthResponse(status="ok" if ok else "degraded", version=__version__, db=db, redis=rd)
