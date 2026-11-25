"""Which runs count as active.

A run that has shown no sign of life for `run_timeout_seconds` is treated as dead (the
worker crashed), so it can never block a chat forever.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from crew.config import Settings
from crew.models import Run
from crew.models.chat import ACTIVE_RUN_STATUSES


def is_active(settings: Settings) -> ColumnElement[bool]:
    cutoff = datetime.now(UTC) - timedelta(seconds=settings.run_timeout_seconds)
    # `updated_at` moves whenever the worker makes progress (or sends a heartbeat).
    return Run.status.in_(ACTIVE_RUN_STATUSES) & (Run.updated_at > cutoff)


async def active_bot_ids(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID
) -> set[uuid.UUID]:
    rows = await session.scalars(
        select(Run.bot_id).where(Run.user_id == user_id, is_active(settings))
    )
    return set(rows.all())


async def active_run_id(
    session: AsyncSession, settings: Settings, chat_id: uuid.UUID
) -> uuid.UUID | None:
    return await session.scalar(
        select(Run.id).where(Run.chat_id == chat_id, is_active(settings)).limit(1)
    )
