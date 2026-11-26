"""Routines that start when something arrives in an app (new email, new message).

Polled once a minute. The first look at a routine only notes what is already there; later
looks start one run when anything new has appeared since.
"""

import json

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew.config import Settings
from crew.connectors.backend import ConnectorBackend, ConnectorError
from crew.models import Bot, Connector, Routine
from crew.routines import service as routines

log = structlog.get_logger(__name__)

EVENTS = {"gmail": ("new_email",), "slack": ("new_message",)}
SEEN_KEEP = 200


async def poll(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    queue: routines.JobQueue,
    settings: Settings,
    backend: ConnectorBackend | None,
) -> int:
    """Returns how many routine runs were started."""
    if backend is None:
        return 0
    started = 0
    async with session_factory() as session:
        waiting = (
            await session.scalars(
                select(Routine).where(
                    Routine.paused.is_(False), Routine.trigger["type"].astext == "connector_event"
                )
            )
        ).all()
        for routine in waiting:
            kind = str(routine.trigger.get("connector", ""))
            event = str(routine.trigger.get("event", ""))
            if event not in EVENTS.get(kind, ()):
                continue
            bot = await session.get(Bot, routine.bot_id)
            connector = await session.scalar(
                select(Connector).where(
                    Connector.user_id == routine.user_id,
                    Connector.kind == kind,
                    Connector.status == "connected",
                )
            )
            # The routine's Bot must be allowed to use the app it listens to.
            if bot is None or connector is None or connector.id not in bot.apps:
                continue
            try:
                ids = await backend.recent_ids(
                    routine.user_id, str(connector.config.get("connection_id", "")), event
                )
            except ConnectorError as error:
                log.info("routine.event_poll_failed", routine_id=str(routine.id), reason=str(error))
                continue
            key = f"routine:{routine.id}:seen"
            stored = await redis.get(key)
            first_look = stored is None
            seen: list[str] = json.loads(stored) if stored else []
            fresh = [item for item in ids if item not in seen]
            # Remember what has been seen (also when there is nothing yet).
            await redis.set(key, json.dumps([*fresh, *seen][:SEEN_KEEP]))
            if first_look or not fresh:
                continue
            try:
                await routines.start_run(session, redis, queue, settings, routine, "event")
                started += 1
            except routines.NotStarted as error:
                await session.rollback()
                log.info("routine.skipped", routine_id=str(routine.id), reason=error.reason)
    return started
