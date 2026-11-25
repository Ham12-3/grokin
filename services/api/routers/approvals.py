"""Approval routes. Logic lives in `crew.approvals.service`."""

import uuid
from typing import Literal

from fastapi import APIRouter

from api.deps import CurrentUser, QueueDep, RedisDep, RegistryDep, SessionDep
from crew.approvals import service
from crew.schemas.approval import ApprovalOut, ApproveRequest, RejectRequest

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(
    user: CurrentUser,
    session: SessionDep,
    status: Literal["pending", "approved", "rejected", "expired"] | None = None,
) -> list[ApprovalOut]:
    return await service.list_approvals(session, user.id, status)


@router.post("/{approval_id}/approve", response_model=ApprovalOut)
async def approve(
    approval_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    queue: QueueDep,
    registry: RegistryDep,
    body: ApproveRequest | None = None,
) -> ApprovalOut:
    edited = body.edited_args if body is not None else None
    return await service.approve(session, redis, queue, registry, user.id, approval_id, edited)


@router.post("/{approval_id}/reject", response_model=ApprovalOut)
async def reject(
    approval_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    queue: QueueDep,
    body: RejectRequest | None = None,
) -> ApprovalOut:
    reason = body.reason if body is not None else None
    return await service.reject(session, redis, queue, user.id, approval_id, reason)
