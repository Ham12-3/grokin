"""Request and response models for Bots, chats and messages."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from crew.schemas.run import ToolCallOut

ApprovalMode = Literal["always_ask", "ask_risky", "never_ask"]


def _clean(value: str) -> str:
    return value.strip()


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    avatar: str | None = Field(default=None, max_length=300)
    job: str = Field(min_length=1, max_length=200)
    instructions: str = Field(default="", max_length=8000)
    approval_mode: ApprovalMode = "ask_risky"

    _strip = field_validator("name", "job", mode="before")(_clean)


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    avatar: str | None = Field(default=None, max_length=300)
    job: str | None = Field(default=None, min_length=1, max_length=200)
    instructions: str | None = Field(default=None, max_length=8000)
    approval_mode: ApprovalMode | None = None

    _strip = field_validator("name", "job", mode="before")(
        lambda value: _clean(value) if isinstance(value, str) else value
    )


class BotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    avatar: str | None
    job: str
    instructions: str
    approval_mode: ApprovalMode
    is_primary: bool
    direct_chat_id: uuid.UUID | None
    working: bool
    created_at: datetime


class ChatCreate(BaseModel):
    bot_ids: list[uuid.UUID] = Field(min_length=1, max_length=6)


class ChatOut(BaseModel):
    id: uuid.UUID
    kind: Literal["direct", "group"]
    title: str | None
    bot_ids: list[uuid.UUID]
    last_message_at: datetime | None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chat_id: uuid.UUID
    role: Literal["user", "bot", "system"]
    bot_id: uuid.UUID | None
    content: str
    # A skill draft or a handoff: see `crew.skills.service` and `crew.tools.handoff`.
    card: dict[str, Any] | None = None
    run_id: uuid.UUID | None
    created_at: datetime


class MessagePage(BaseModel):
    """Oldest first. `has_more` means older messages exist before `items[0]`."""

    items: list[MessageOut]
    has_more: bool
    active_run_id: uuid.UUID | None
    # Tool steps of the runs behind these messages, oldest first.
    tool_calls: list[ToolCallOut]


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=32000)
    # Set when the user picked a skill with "/": its steps are added to this run's prompt.
    skill_id: uuid.UUID | None = None

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message is empty")
        return value


class SendMessageResponse(BaseModel):
    message: MessageOut
    run_id: uuid.UUID
