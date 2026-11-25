"""Request and response models for approvals."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


class ApprovalPreview(BaseModel):
    """What the card shows. `fields` are the tool's arguments and may be edited."""

    kind: Literal["email", "post", "purchase", "generic"]
    fields: dict[str, Any]
    context: dict[str, str] = Field(default_factory=dict)


class ApprovalOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    chat_id: uuid.UUID | None
    bot_id: uuid.UUID
    tool_call_id: uuid.UUID
    tool: str
    title: str
    preview: ApprovalPreview
    status: ApprovalStatus
    created_at: datetime
    resolved_at: datetime | None


class ApproveRequest(BaseModel):
    # The whole argument object, as edited by the user. Checked against the tool's schema.
    edited_args: dict[str, Any] | None = None


class RejectRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)
