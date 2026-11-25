"""Tool call lookups shared by the chat and run services."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crew.models import ToolCall


async def tool_calls_for_runs(
    session: AsyncSession, user_id: uuid.UUID, run_ids: set[uuid.UUID]
) -> list[ToolCall]:
    if not run_ids:
        return []
    rows = await session.scalars(
        select(ToolCall)
        .where(ToolCall.run_id.in_(run_ids), ToolCall.user_id == user_id)
        .order_by(ToolCall.id)
    )
    return list(rows.all())
