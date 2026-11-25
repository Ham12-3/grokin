"""Chat and message routes. Logic lives in `crew.chats.service`."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from api.deps import CurrentUser, QueueDep, RedisDep, SessionDep, SettingsDep
from crew.chats import service
from crew.schemas.chat import (
    ChatCreate,
    ChatOut,
    MessageOut,
    MessagePage,
    SendMessageRequest,
    SendMessageResponse,
)
from crew.schemas.run import ToolCallOut
from crew.skills import service as skills

router = APIRouter(prefix="/chats", tags=["chats"])


@router.get("", response_model=list[ChatOut])
async def list_chats(user: CurrentUser, session: SessionDep) -> list[ChatOut]:
    return await service.list_chats(session, user.id)


@router.post("", response_model=ChatOut)
async def open_chat(body: ChatCreate, user: CurrentUser, session: SessionDep) -> ChatOut:
    return await service.open_chat(session, user.id, body.bot_ids)


@router.get("/{chat_id}/messages", response_model=MessagePage)
async def list_messages(
    chat_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
    before: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> MessagePage:
    page = await service.list_messages(
        session, settings, user.id, chat_id, before=before, limit=limit
    )
    return MessagePage(
        items=[MessageOut.model_validate(message) for message in page.items],
        has_more=page.has_more,
        active_run_id=page.active_run_id,
        tool_calls=[ToolCallOut.model_validate(call) for call in page.tool_calls],
    )


@router.post("/{chat_id}/messages", response_model=SendMessageResponse, status_code=202)
async def send_message(
    chat_id: uuid.UUID,
    body: SendMessageRequest,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> SendMessageResponse:
    message, run_id = await service.send_message(
        session,
        redis,
        queue,
        settings,
        user.id,
        chat_id,
        content=body.content,
        skill_id=body.skill_id,
    )
    return SendMessageResponse(message=MessageOut.model_validate(message), run_id=run_id)


@router.post("/{chat_id}/skill-drafts/{message_id}/save", response_model=MessageOut)
async def save_skill_draft(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
) -> MessageOut:
    """The user accepts a skill the Bot drafted. Only this creates the skill."""
    message = await skills.save_draft(session, redis, user.id, chat_id, message_id)
    return MessageOut.model_validate(message)


@router.post("/{chat_id}/skill-drafts/{message_id}/cancel", response_model=MessageOut)
async def cancel_skill_draft(
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
) -> MessageOut:
    message = await skills.cancel_draft(session, redis, user.id, chat_id, message_id)
    return MessageOut.model_validate(message)
