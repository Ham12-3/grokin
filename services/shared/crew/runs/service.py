"""Run lookups and cancel. Every query filters by `user_id`."""

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crew import events
from crew.agent.loop import request_cancel, request_pause, request_resume
from crew.config import Settings
from crew.errors import AppError
from crew.models import Approval, Message, Run, ToolCall


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
    if run.status == "waiting_approval":
        return await _cancel_waiting(session, redis, user_id, run)
    if run.status in ("running", "paused"):
        # A paused run is still alive in the worker, waiting: it can be stopped too.
        await request_cancel(redis, run.id)
    return run.status


async def _cancel_waiting(session: AsyncSession, redis: Redis, user_id: uuid.UUID, run: Run) -> str:
    """Stops a run that waits for approval. No worker holds it, so it ends here."""
    now = datetime.now(UTC)
    claimed = await session.execute(
        update(Run)
        .where(Run.id == run.id, Run.status == "waiting_approval")
        .values(status="cancelled", finished_at=now)
        .returning(Run.id)
    )
    if claimed.first() is None:
        await session.refresh(run)
        return run.status  # answered a moment ago: the worker has it again
    expired = (
        await session.scalars(
            update(Approval)
            .where(Approval.run_id == run.id, Approval.status == "pending")
            .values(status="expired", resolved_at=now)
            .returning(Approval.id)
        )
    ).all()
    await session.execute(
        update(ToolCall)
        .where(ToolCall.run_id == run.id, ToolCall.status == "waiting_approval")
        .values(status="rejected", result_summary="Stopped", finished_at=now)
    )
    message_id = await session.scalar(
        select(Message.id).where(Message.run_id == run.id, Message.role == "bot").limit(1)
    )
    await session.commit()
    channel = events.user_channel(user_id)
    for approval_id in expired:
        await events.publish(
            redis,
            channel,
            "approval.resolved",
            {"approval_id": str(approval_id), "status": "expired"},
        )
    await events.publish(
        redis,
        channel,
        "run.status",
        {
            "run_id": str(run.id),
            "chat_id": str(run.chat_id),
            "bot_id": str(run.bot_id),
            "status": "cancelled",
            "message_id": str(message_id) if message_id else None,
            "message_kept": message_id is not None,
        },
    )
    return "cancelled"


async def pause_run(
    session: AsyncSession, redis: Redis, settings: Settings, user_id: uuid.UUID, run_id: uuid.UUID
) -> str:
    """Asks a running run to wait (Take over). It pauses before its next step or tool."""
    run = await get_run(session, user_id, run_id)
    if run.status == "running":
        await request_pause(redis, run.id, "user", settings.takeover_timeout_seconds + 60)
    return run.status


async def resume_run(
    session: AsyncSession, redis: Redis, user_id: uuid.UUID, run_id: uuid.UUID
) -> str:
    """Lets a paused run continue (Give back)."""
    run = await get_run(session, user_id, run_id)
    await request_resume(redis, run.id)
    return run.status
