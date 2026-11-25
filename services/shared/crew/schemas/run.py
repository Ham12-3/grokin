"""Response models for runs and tool calls."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

RunStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "needs_review",
]


class ToolCallOut(BaseModel):
    """Safe to show: the summaries never contain secrets. Raw arguments are not exposed."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    step: int
    tool: str
    risk: Literal["safe", "risky"]
    status: Literal["pending", "waiting_approval", "running", "ok", "error", "rejected"]
    summary: str
    result_summary: str | None
    started_at: datetime | None
    finished_at: datetime | None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chat_id: uuid.UUID | None
    bot_id: uuid.UUID
    status: RunStatus
    steps: int
    input_tokens: int
    output_tokens: int
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class CancelResponse(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
