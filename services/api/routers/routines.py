"""Routine routes. Logic lives in `crew.routines.service`."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Response

from api.deps import CurrentUser, QueueDep, RedisDep, SessionDep, SettingsDep
from crew.routines import schedule, service
from crew.schemas.routine import (
    CronPreview,
    CronPreviewRequest,
    PauseAllResponse,
    RoutineCreate,
    RoutineOut,
    RoutineRunOut,
    RoutineUpdate,
)
from crew.schemas.run import CancelResponse

router = APIRouter(tags=["routines"])


@router.get("/bots/{bot_id}/routines", response_model=list[RoutineOut])
async def list_routines(
    bot_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[RoutineOut]:
    return await service.list_routines(session, user.id, bot_id)


@router.post("/bots/{bot_id}/routines", response_model=RoutineOut, status_code=201)
async def create_routine(
    bot_id: uuid.UUID,
    body: RoutineCreate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> RoutineOut:
    return await service.create_routine(session, settings, user.id, bot_id, body)


@router.post("/routines/preview", response_model=CronPreview)
async def preview(body: CronPreviewRequest, user: CurrentUser) -> CronPreview:
    """The next three times a schedule would run, to show before saving."""
    return CronPreview(
        next_runs=schedule.preview(body.cron.strip(), body.timezone, datetime.now(UTC))
    )


@router.post("/routines/pause-all", response_model=PauseAllResponse)
async def pause_all(user: CurrentUser, session: SessionDep) -> PauseAllResponse:
    return PauseAllResponse(paused=await service.pause_all(session, user.id))


@router.patch("/routines/{routine_id}", response_model=RoutineOut)
async def update_routine(
    routine_id: uuid.UUID,
    body: RoutineUpdate,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> RoutineOut:
    return await service.update_routine(session, settings, user.id, routine_id, body)


@router.delete("/routines/{routine_id}", status_code=204)
async def delete_routine(routine_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    await service.delete_routine(session, user.id, routine_id)
    return Response(status_code=204)


@router.post("/routines/{routine_id}/pause", response_model=RoutineOut)
async def pause(routine_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RoutineOut:
    return await service.set_paused(session, user.id, routine_id, True)


@router.post("/routines/{routine_id}/resume", response_model=RoutineOut)
async def resume(routine_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RoutineOut:
    return await service.set_paused(session, user.id, routine_id, False)


@router.post("/routines/{routine_id}/test", response_model=CancelResponse, status_code=202)
async def test_run(
    routine_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> CancelResponse:
    run_id = await service.test_run(session, redis, queue, settings, user.id, routine_id)
    return CancelResponse(run_id=run_id, status="queued")


@router.get("/routines/{routine_id}/runs", response_model=list[RoutineRunOut])
async def list_runs(
    routine_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[RoutineRunOut]:
    return await service.list_runs(session, user.id, routine_id)
