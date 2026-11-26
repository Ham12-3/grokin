"""Request and response models for routines."""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from crew.schemas.run import RunStatus, ToolCallOut


class CronTrigger(BaseModel):
    type: Literal["cron"] = "cron"
    cron: str = Field(min_length=9, max_length=100)  # five fields, for example "0 9 * * 1-5"
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class WebhookTrigger(BaseModel):
    type: Literal["webhook"] = "webhook"


class ConnectorEventTrigger(BaseModel):
    """Stored now, fired once connectors exist (phase 8)."""

    type: Literal["connector_event"] = "connector_event"
    connector: str = Field(min_length=1, max_length=60)
    event: str = Field(min_length=1, max_length=120)


Trigger = Annotated[
    CronTrigger | WebhookTrigger | ConnectorEventTrigger, Field(discriminator="type")
]


class RoutineCreate(BaseModel):
    skill_id: uuid.UUID
    trigger: Trigger
    notify: bool = False


class RoutineUpdate(BaseModel):
    skill_id: uuid.UUID | None = None
    trigger: Trigger | None = None
    notify: bool | None = None


class LastRun(BaseModel):
    run_id: uuid.UUID
    status: RunStatus
    at: datetime


class RoutineOut(BaseModel):
    id: uuid.UUID
    bot_id: uuid.UUID
    skill_id: uuid.UUID
    skill_name: str
    skill_slug: str
    trigger: Trigger
    notify: bool
    paused: bool
    next_run_at: datetime | None
    last_run: LastRun | None
    # Only in the answer to creating a webhook routine (or making a new secret): the URL
    # holds the secret and is never shown again.
    webhook_url: str | None = None


class RoutineRunOut(BaseModel):
    """One past run of a routine, with what the Bot said and did."""

    run_id: uuid.UUID
    status: RunStatus
    source: str  # schedule | webhook | test
    created_at: datetime
    finished_at: datetime | None
    error: str | None
    reply: str
    tool_calls: list[ToolCallOut]


class CronPreviewRequest(BaseModel):
    cron: str = Field(min_length=1, max_length=100)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)


class CronPreview(BaseModel):
    next_runs: list[datetime]


class PauseAllResponse(BaseModel):
    paused: int
