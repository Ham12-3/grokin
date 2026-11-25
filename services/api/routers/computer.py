"""Computer routes and the live screen WebSocket. Logic lives in `crew.computer`."""

import time
import uuid

from fastapi import APIRouter, WebSocket

from api.deps import CurrentUser, ProviderDep, RedisDep, SessionDep, SettingsDep
from api.ws import authenticate
from crew.computer import service
from crew.computer.provider import ComputerError
from crew.computer.vnc import CLOSE_UNAUTHORIZED, CLOSE_UNAVAILABLE, proxy
from crew.errors import AppError
from crew.models import Computer
from crew.schemas.computer import ComputerOut

router = APIRouter(prefix="/computer", tags=["computer"])

VNC_PROTOCOL = "binary"


def _unavailable(error: ComputerError) -> AppError:
    return AppError(503, "computer_unavailable", str(error))


@router.get("", response_model=ComputerOut)
async def get_computer(
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    provider: ProviderDep,
) -> ComputerOut:
    computer = await service.get_computer(session, settings, user.id)
    await service.refresh_status(session, redis, provider, computer)
    return ComputerOut.model_validate(computer)


@router.post("/start", response_model=ComputerOut)
async def start_computer(
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    provider: ProviderDep,
) -> ComputerOut:
    try:
        computer, _ = await service.start_computer(
            session, redis, provider, settings, user.id, by_user=True
        )
    except ComputerError as error:
        raise _unavailable(error) from error
    return ComputerOut.model_validate(computer)


@router.post("/stop", response_model=ComputerOut)
async def stop_computer(
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
    provider: ProviderDep,
) -> ComputerOut:
    try:
        computer = await service.stop_computer(session, redis, provider, settings, user.id)
    except ComputerError as error:
        raise _unavailable(error) from error
    return ComputerOut.model_validate(computer)


@router.websocket("/{computer_id}/vnc")
async def vnc(websocket: WebSocket, computer_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    """The live screen of the Bot's display. Only the computer's owner gets through."""
    state = websocket.app.state
    identity = await authenticate(websocket)
    if identity is None:
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    user_id, expires_at = identity

    async with state.session_factory() as session:
        computer = await session.get(Computer, computer_id)
        # Same refusal for "not yours" and "does not exist".
        if (
            computer is None
            or computer.user_id != user_id
            or not await service.owned_bot(session, user_id, bot_id)
        ):
            await websocket.close(code=CLOSE_UNAUTHORIZED)
            return
        running = computer.status == "running"

    try:
        if not running or await state.provider.state(user_id) != "running":
            raise ComputerError("Your computer is not running.")
        handle = await state.provider.ensure(user_id)
        display = await service.display_for_bot(state.redis, user_id, bot_id)
        await state.provider.start_display(handle, display)
        upstream = state.provider.vnc_url(handle, display)
    except ComputerError:
        await websocket.close(code=CLOSE_UNAVAILABLE)
        return

    await websocket.accept(subprotocol=VNC_PROTOCOL)
    await service.touch(state.session_factory, user_id)
    await proxy(websocket, upstream, expires_in=expires_at - time.time())
