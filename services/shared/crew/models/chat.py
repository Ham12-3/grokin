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
    LargeBinary,
    Text,
    UniqueConstraint,
    Uuid,
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
    # Connector ids this Bot may use (the Apps tab). Empty means none.
    apps: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))


class Chat(Base, IdMixin, TimestampMixin):
    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)  # direct | group | routine
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
    routine_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("routines.id", ondelete="CASCADE")
    )
    # queued | running | waiting_approval | paused | completed | failed | cancelled | needs_review
    status: Mapped[str] = mapped_column(Text)
    steps: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    input_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    # The messages added during this run (assistant turns and tool results), so a run can
    # be rebuilt exactly when it resumes after an approval.
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, server_default=text("'[]'"))
    # The skill the user invoked with "/slug": its steps go into this run's prompt.
    skill_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("skills.id", ondelete="SET NULL"))
    # Group chats: which Bot turn this is for one user message (1 to 6), and the Bots
    # still to answer after this one, in order.
    turn: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    queue: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid), server_default=text("'{}'"))
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
    # Drafted by a routine: nobody was waiting, the run ended `needs_review`.
    from_routine: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
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


class Memory(Base, IdMixin, TimestampMixin):
    """One short line a Bot remembers about its user. The user can edit or delete it."""

    __tablename__ = "memories"
    __table_args__ = (Index("ix_memories_bot", "bot_id"),)

    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)


class Skill(Base, IdMixin, TimestampMixin):
    """A saved procedure a Bot can run again. `slug` is what follows "/" in the composer."""

    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("bot_id", "slug"),)

    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    steps: Mapped[str] = mapped_column(Text)  # markdown
    rules: Mapped[str] = mapped_column(Text, server_default=text("''"))


class Routine(Base, IdMixin, TimestampMixin):
    """A skill that runs by itself: on a schedule, from a webhook, or (later) on an event."""

    __tablename__ = "routines"
    __table_args__ = (
        Index("ix_routines_due", "next_run_at", postgresql_where=text("NOT paused")),
        Index("ix_routines_bot", "bot_id"),
    )

    bot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bots.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    skill_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("skills.id", ondelete="CASCADE"))
    # {type:"cron",cron,timezone} | {type:"webhook"} | {type:"connector_event",connector,event}
    trigger: Mapped[dict[str, Any]] = mapped_column(JSONB)
    webhook_secret_hash: Mapped[str | None] = mapped_column(Text)
    notify: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    paused: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Each routine has its own chat: its runs never wait behind (or block) the user's chat.
    chat_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("chats.id", ondelete="SET NULL"))


class VaultItem(Base, IdMixin, TimestampMixin):
    """One secret. Only ciphertext is stored; see `crew.vault.crypto`."""

    __tablename__ = "vault_items"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)  # used in {{vault:name}}
    type: Mapped[str] = mapped_column(Text)  # login | api_key | card | note | oauth_token
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)  # AES-256-GCM
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    wrapped_data_key: Mapped[bytes] = mapped_column(LargeBinary)
    # Which key wrapped the data key: "master" or "kms".
    wrapped_by: Mapped[str] = mapped_column(Text, server_default=text("'master'"))


class Connector(Base, IdMixin, TimestampMixin):
    """An app the user connected (Gmail, Slack, ...) or a custom MCP server."""

    __tablename__ = "connectors"
    __table_args__ = (Index("ix_connectors_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)  # gmail | gcal | slack | notion | mcp
    name: Mapped[str] = mapped_column(Text)
    # MCP URL and tool list, or the provider's connection id. Never secrets.
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'"))
    # Vault item holding tokens or headers, if any.
    secret_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("vault_items.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, server_default=text("'connected'"))


class LibraryItem(Base, IdMixin, TimestampMixin):
    """Something a Bot made for the user to keep: a copy lives in storage for download."""

    __tablename__ = "library_items"
    __table_args__ = (Index("ix_library_items_user", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    bot_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("bots.id", ondelete="SET NULL"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(Text)  # file | page | result
    title: Mapped[str] = mapped_column(Text)
    path: Mapped[str | None] = mapped_column(Text)  # /workspace/outputs/...
    storage_key: Mapped[str | None] = mapped_column(Text)
    mime: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)


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
