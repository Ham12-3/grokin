"""ARQ worker entry point: `uv run arq worker.main.WorkerSettings`."""

from typing import Any, ClassVar

from arq.connections import RedisSettings

from crew.config import get_settings


async def ping(ctx: dict[str, Any]) -> str:
    """Placeholder job so the worker starts. Agent runs arrive in phase 2."""
    return "pong"


class WorkerSettings:
    functions: ClassVar[list[Any]] = [ping]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
