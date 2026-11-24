"""Daily token usage per user (UTC days)."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from crew.models import UsageDaily


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


async def add_usage(
    session: AsyncSession, user_id: uuid.UUID, *, input_tokens: int, output_tokens: int
) -> None:
    """Adds to today's totals. The caller commits."""
    statement = insert(UsageDaily).values(
        user_id=user_id,
        day=datetime.now(UTC).date(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[UsageDaily.user_id, UsageDaily.day],
            set_={
                "input_tokens": UsageDaily.input_tokens + statement.excluded.input_tokens,
                "output_tokens": UsageDaily.output_tokens + statement.excluded.output_tokens,
            },
        )
    )


async def usage_today(session: AsyncSession, user_id: uuid.UUID) -> Usage:
    row = await session.scalar(
        select(UsageDaily).where(
            UsageDaily.user_id == user_id, UsageDaily.day == datetime.now(UTC).date()
        )
    )
    if row is None:
        return Usage(0, 0)
    return Usage(row.input_tokens, row.output_tokens)
