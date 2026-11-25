"""Bots, chats, messages, runs and daily usage."""

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from crew.db import Base
from crew.models.base import IdMixin, TimestampMixin

APPROVAL_MODES = ("always_ask", "ask_risky", "never_ask")
ACTIVE_RUN_STATUSES = ("queued", "running", "paused")
# Waiting for the user: alive however long it takes (no worker holds it).
WAITING_RUN_STATUS = "waiting_approval"


class Bot(Base, IdMixin, TimestampMixin):
    __tablename__ = "bots"
    __table_args__ = (
        Index("one_primary_bot", "user_id", unique=True, postgresql_where=text("is_primary")),
        Index("ix_bots_user", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    avatar: Mapped[str | None] = mapped_column(Text)  # emoji or image URL
    job: Mapped[str] = mapped_column(Text)  # one line
    instructions: Mapped[str] = mapped_column(Text, server_default=text("''"))
    approval_mode: Mapped[str] = mapped_column(Text, server_default=text("'ask_risky'"))
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    enabled_tools: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'"))


class Chat(Base, IdMixin, TimestampMixin):
    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)  # direct | group
    title: Mapped[str | None] = mapped_column(Text)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ChatMember(Base):
    __tablename__ = "chat_members"
    __table_args__ = (Index("ix_chat_members_bot", "bot_id"),)

    chat_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"), primary_key=True
    )
    bot_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("bots.id", ondelete="CASCADE"), primary_key=True
    )


class Run(Base, IdMixin, TimestampMixin):
    __tablename__ = "runs"
    __table_args__ = (Index("ix_runs_chat_status", "chat_id", "status"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chats.id", ondelete="SET NULL"))
    routine_id: Mapped[uuid.UUID | None] = mapped_column()  # FK arrives with routines (phase 7)
    # queued | running | waiting_approval | paused | completed | failed | cancelled | needs_review
    status: Mapped[str] = mapped_column(Text)
    steps: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    input_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    # The messages added during this run (assistant turns and tool results), so a run can
    # be rebuilt exactly when it resumes after an approval.
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    # Results of the current step's tool calls so far, kept while one of them waits for
    # approval, so a resumed run never repeats a tool that already ran.
    pending_results: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ToolCall(Base, IdMixin, TimestampMixin):
    """One tool call. Written before the tool runs and updated after it finishes."""

    __tablename__ = "tool_calls"
    __table_args__ = (Index("ix_tool_calls_run", "run_id", "id"),)

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    step: Mapped[int] = mapped_column(Integer)
    llm_tool_use_id: Mapped[str] = mapped_column(Text)  # the id Claude gave this call
    tool: Mapped[str] = mapped_column(Text)
    args: Mapped[dict[str, Any]] = mapped_column(JSONB)  # vault placeholders, never raw secrets
    risk: Mapped[str] = mapped_column(Text)  # safe | risky
    # pending | waiting_approval | running | ok | error | rejected
    status: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text, server_default=text("''"))  # safe text for the UI
    result_summary: Mapped[str | None] = mapped_column(Text)
    result_ref: Mapped[str | None] = mapped_column(Text)  # pointer to large output (later)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base, IdMixin, TimestampMixin):
    __tablename__ = "messages"
    # Ids are UUID v7, so ordering by id is ordering by time.
    __table_args__ = (Index("ix_messages_chat_id_id", "chat_id", "id"),)

    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(Text)  # user | bot | system
    bot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bots.id", ondelete="SET NULL"))
    content: Mapped[str] = mapped_column(Text)
    card: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))


class Approval(Base, IdMixin, TimestampMixin):
    """A risky tool call waiting for the user. Only the approve endpoint sets `approved`."""

    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("tool_call_id"),
        Index("ix_approvals_user_status", "user_id", "status"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    tool_call_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tool_calls.id", ondelete="CASCADE"))
    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    chat_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chats.id", ondelete="SET NULL"))
    tool: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)  # "Send email to sam@acme.com"
    preview: Mapped[dict[str, Any]] = mapped_column(JSONB)  # what the user sees and can edit
    # pending | approved | rejected | expired
    status: Mapped[str] = mapped_column(Text, server_default=text("'pending'"))
    edited_args: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)  # why the user rejected it
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set when the worker runs the approved call: an approval is good for one execution.
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ConnectorLog(Base, IdMixin):
    """What the fake connector tools "sent" (email_send, social_post). Dev and tests only."""

    __tablename__ = "connector_log"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    tool: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Computer(Base, IdMixin, TimestampMixin):
    """The user's one cloud computer."""

    __tablename__ = "computers"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    provider: Mapped[str] = mapped_column(Text)  # docker | e2b | local
    external_id: Mapped[str | None] = mapped_column(Text)
    # starting | running | paused | stopped | error
    status: Mapped[str] = mapped_column(Text, server_default=text("'stopped'"))
    control_token_hash: Mapped[str | None] = mapped_column(Text)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UsageDaily(Base):
    __tablename__ = "usage_daily"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
