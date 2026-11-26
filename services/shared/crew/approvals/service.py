"""Approvals: list, approve, reject. Every query filters by `user_id`.

Approving or rejecting is the ONLY way a waiting run continues: it is queued again and the
agent loop picks up from the database. The model has no path to these functions.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crew import audit, events
from crew.errors import AppError
from crew.models import Approval, Bot, Run
from crew.schemas.approval import ApprovalOut, ApprovalPreview
from crew.tools.connectors import registry_for_bot
from crew.tools.registry import ToolRegistry, validation_message


class JobQueue(Protocol):
    async def enqueue_job(self, function: str, *args: object) -> object: ...


def approval_out(approval: Approval) -> ApprovalOut:
    return ApprovalOut(
        id=approval.id,
        run_id=approval.run_id,
        chat_id=approval.chat_id,
        bot_id=approval.bot_id,
        tool_call_id=approval.tool_call_id,
        tool=approval.tool,
        title=approval.title,
        preview=ApprovalPreview.model_validate(approval.preview),
        status=approval.status,
        created_at=approval.created_at,
        resolved_at=approval.resolved_at,
        from_routine=approval.from_routine,
    )


async def list_approvals(
    session: AsyncSession, user_id: uuid.UUID, status: str | None
) -> list[ApprovalOut]:
    query = select(Approval).where(Approval.user_id == user_id)
    if status is not None:
        query = query.where(Approval.status == status)
    rows = await session.scalars(query.order_by(Approval.id.desc()).limit(200))
    return [approval_out(row) for row in rows.all()]


async def _resolve(
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    user_id: uuid.UUID,
    approval_id: uuid.UUID,
    *,
    status: str,
    edited_args: dict[str, Any] | None = None,
    reason: str | None = None,
    registry: ToolRegistry | None = None,
) -> ApprovalOut:
    # Same answer for "not yours" and "does not exist". Locked, so two clicks cannot both win.
    approval = await session.scalar(
        select(Approval)
        .where(Approval.id == approval_id, Approval.user_id == user_id)
        .with_for_update()
    )
    if approval is None:
        raise AppError(404, "approval_not_found", "That approval does not exist.")
    if approval.status != "pending":
        raise AppError(409, "approval_resolved", "This was already answered.")

    if edited_args is not None:
        bot = await session.get(Bot, approval.bot_id)
        if registry is not None and bot is not None:
            # App and MCP tools exist only for the Bots allowed to use them.
            registry = await registry_for_bot(session, registry, bot)
        tool = registry.get(approval.tool) if registry is not None else None
        problem = "This tool no longer exists." if tool is None else None
        if tool is not None:
            problem = validation_message(tool, edited_args)
        if problem is not None:
            raise AppError(422, "invalid_edit", problem)

    # The run goes back to the worker only if it is still waiting for this.
    requeued = await session.execute(
        update(Run)
        .where(
            Run.id == approval.run_id,
            Run.user_id == user_id,
            # `needs_review` is a routine run that drafted this and ended without waiting.
            Run.status.in_(("waiting_approval", "needs_review")),
        )
        .values(status="queued")
        .returning(Run.id)
    )
    if requeued.first() is None:
        approval.status = "expired"
        approval.resolved_at = datetime.now(UTC)
        await session.commit()
        raise AppError(409, "approval_expired", "That request is no longer waiting.")

    approval.status = status
    approval.resolved_at = datetime.now(UTC)
    approval.reason = reason
    if status == "approved" and edited_args is not None:
        approval.edited_args = edited_args
        approval.preview = {**approval.preview, "fields": edited_args}
    audit.record(
        session,
        user_id=user_id,
        actor="user",
        action=f"approval.{'approve' if status == 'approved' else 'reject'}",
        target=str(approval.id),
        detail={"tool": approval.tool, "edited": edited_args is not None},
    )
    await session.commit()
    await session.refresh(approval)

    channel = events.user_channel(user_id)
    await events.publish(
        redis, channel, "approval.resolved", {"approval_id": str(approval.id), "status": status}
    )
    await events.publish(
        redis,
        channel,
        "run.status",
        {
            "run_id": str(approval.run_id),
            "chat_id": str(approval.chat_id),
            "bot_id": str(approval.bot_id),
            "status": "queued",
        },
    )
    await queue.enqueue_job("run_agent", str(approval.run_id))
    return approval_out(approval)


async def approve(
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    registry: ToolRegistry,
    user_id: uuid.UUID,
    approval_id: uuid.UUID,
    edited_args: dict[str, Any] | None,
) -> ApprovalOut:
    return await _resolve(
        session,
        redis,
        queue,
        user_id,
        approval_id,
        status="approved",
        edited_args=edited_args,
        registry=registry,
    )


async def reject(
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    user_id: uuid.UUID,
    approval_id: uuid.UUID,
    reason: str | None,
) -> ApprovalOut:
    return await _resolve(
        session, redis, queue, user_id, approval_id, status="rejected", reason=reason
    )
