"""Audit log writes. Never put secrets or tokens in `detail`."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from crew.models import AuditLog


def record(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    actor: str,
    action: str,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Adds a row to the session. The caller commits."""
    session.add(AuditLog(user_id=user_id, actor=actor, action=action, target=target, detail=detail))
