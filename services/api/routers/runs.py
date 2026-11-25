"""Run routes. Logic lives in `crew.runs.service`."""

import uuid

from fastapi import APIRouter

from api.deps import CurrentUser, RedisDep, SessionDep, SettingsDep
from crew.runs import service
from crew.schemas.run import CancelResponse, RunOut, ToolCallOut

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> RunOut:
    return RunOut.model_validate(await service.get_run(session, user.id, run_id))


@router.get("/{run_id}/tool-calls", response_model=list[ToolCallOut])
async def list_tool_calls(
    run_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> list[ToolCallOut]:
    rows = await service.list_tool_calls(session, user.id, run_id)
    return [ToolCallOut.model_validate(row) for row in rows]


@router.post("/{run_id}/cancel", response_model=CancelResponse, status_code=202)
async def cancel_run(
    run_id: uuid.UUID, user: CurrentUser, session: SessionDep, redis: RedisDep
) -> CancelResponse:
    status = await service.cancel_run(session, redis, user.id, run_id)
    return CancelResponse(run_id=run_id, status=status)


@router.post("/{run_id}/pause", response_model=CancelResponse, status_code=202)
async def pause_run(
    run_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    redis: RedisDep,
    settings: SettingsDep,
) -> CancelResponse:
    status = await service.pause_run(session, redis, settings, user.id, run_id)
    return CancelResponse(run_id=run_id, status=status)


@router.post("/{run_id}/resume", response_model=CancelResponse, status_code=202)
async def resume_run(
    run_id: uuid.UUID, user: CurrentUser, session: SessionDep, redis: RedisDep
) -> CancelResponse:
    status = await service.resume_run(session, redis, user.id, run_id)
    return CancelResponse(run_id=run_id, status=status)
