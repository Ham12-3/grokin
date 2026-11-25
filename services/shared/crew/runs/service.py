"""Run lookups and cancel. Every query filters by `user_id`."""

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crew import events
from crew.agent.loop import request_cancel
from crew.errors import AppError
from crew.models import Run, ToolCall


def not_found() -> AppError:
    return AppError(404, "run_not_found", "That run does not exist.")


async def get_run(session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID) -> Run:
    run = await session.scalar(select(Run).where(Run.id == run_id, Run.user_id == user_id))
    if run is None:
        raise not_found()
    return run


async def list_tool_calls(
    session: AsyncSession, user_id: uuid.UUID, run_id: uuid.UUID
) -> list[ToolCall]:
    run = await get_run(session, user_id, run_id)
    rows = await session.scalars(
        select(ToolCall)
        .where(ToolCall.run_id == run.id, ToolCall.user_id == user_id)
        .order_by(ToolCall.id)
    )
    return list(rows.all())


async def cancel_run(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, run_id: uuid.UUID
) -> str:
    """Stops a run. Returns its status now: a running one stops within a second or so."""
    run = await get_run(session, user_id, run_id)
    if run.status == "queued":
        # No worker has it yet: cancel it here. The worker's claim will then find nothing.
        claimed = await session.execute(
            update(Run)
            .where(Run.id == run.id, Run.status == "queued")
            .values(status="cancelled", finished_at=datetime.now(UTC))
            .returning(Run.id)
        )
        if claimed.first() is not None:
            await session.commit()
            await events.publish(
                redis,
                events.user_channel(user_id),
                "run.status",
                {
                    "run_id": str(run.id),
                    "chat_id": str(run.chat_id),
                    "bot_id": str(run.bot_id),
                    "status": "cancelled",
                },
            )
            return "cancelled"
        await session.refresh(run)
    if run.status == "running":
        await request_cancel(redis, run.id)
    return run.status
