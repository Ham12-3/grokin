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
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from crew.db import Base
from crew.models.base import IdMixin, TimestampMixin

APPROVAL_MODES = ("always_ask", "ask_risky", "never_ask")
ACTIVE_RUN_STATUSES = ("queued", "running")


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


class UsageDaily(Base):
    __tablename__ = "usage_daily"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    input_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
