"""Bot routes. Logic lives in `crew.bots.service`."""

import uuid

from fastapi import APIRouter, Response

from api.deps import CurrentUser, SessionDep, SettingsDep
from crew.bots import service
from crew.bots.service import BotView
from crew.schemas.chat import BotCreate, BotOut, BotUpdate

router = APIRouter(prefix="/bots", tags=["bots"])


def _out(view: BotView) -> BotOut:
    bot = view.bot
    return BotOut(
        id=bot.id,
        name=bot.name,
        avatar=bot.avatar,
        job=bot.job,
        instructions=bot.instructions,
        approval_mode=bot.approval_mode,
        is_primary=bot.is_primary,
        direct_chat_id=view.direct_chat_id,
        working=view.working,
        created_at=bot.created_at,
    )


@router.get("", response_model=list[BotOut])
async def list_bots(user: CurrentUser, session: SessionDep, settings: SettingsDep) -> list[BotOut]:
    return [_out(view) for view in await service.list_bots(session, settings, user.id)]


@router.post("", response_model=BotOut, status_code=201)
async def create_bot(
    body: BotCreate, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> BotOut:
    return _out(await service.create_bot(session, settings, user.id, body))


@router.get("/{bot_id}", response_model=BotOut)
async def get_bot(
    bot_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> BotOut:
    return _out(await service.get_bot(session, settings, user.id, bot_id))


@router.patch("/{bot_id}", response_model=BotOut)
async def update_bot(
    bot_id: uuid.UUID,
    body: BotUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> BotOut:
    return _out(await service.update_bot(session, settings, user.id, bot_id, body))


@router.delete("/{bot_id}", status_code=204)
async def delete_bot(bot_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    await service.delete_bot(session, user.id, bot_id)
    return Response(status_code=204)


@router.post("/{bot_id}/primary", response_model=BotOut)
async def make_primary(
    bot_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> BotOut:
    return _out(await service.set_primary(session, settings, user.id, bot_id))
