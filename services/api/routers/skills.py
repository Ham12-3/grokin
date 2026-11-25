"""Memory and skill routes. Logic lives in `crew.memory.service` and `crew.skills.service`."""

import uuid

from fastapi import APIRouter, Response

from api.deps import CurrentUser, SessionDep
from crew.memory import service as memory
from crew.schemas.memory import MemoryOut, MemoryWrite, SkillCreate, SkillOut, SkillUpdate
from crew.skills import service as skills

router = APIRouter(tags=["memory and skills"])


@router.get("/bots/{bot_id}/memory", response_model=list[MemoryOut])
async def list_memory(bot_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[MemoryOut]:
    rows = await memory.list_memory(session, user.id, bot_id)
    return [MemoryOut.model_validate(row) for row in rows]


@router.post("/bots/{bot_id}/memory", response_model=MemoryOut, status_code=201)
async def add_memory(
    bot_id: uuid.UUID, body: MemoryWrite, user: CurrentUser, session: SessionDep
) -> MemoryOut:
    row, _ = await memory.add_memory(session, user.id, bot_id, body.text)
    return MemoryOut.model_validate(row)


@router.patch("/bots/{bot_id}/memory/{line_id}", response_model=MemoryOut)
async def update_memory(
    bot_id: uuid.UUID,
    line_id: uuid.UUID,
    body: MemoryWrite,
    user: CurrentUser,
    session: SessionDep,
) -> MemoryOut:
    row = await memory.update_memory(session, user.id, bot_id, line_id, body.text)
    return MemoryOut.model_validate(row)


@router.delete("/bots/{bot_id}/memory/{line_id}", status_code=204)
async def delete_memory(
    bot_id: uuid.UUID, line_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> Response:
    await memory.delete_memory(session, user.id, bot_id, line_id)
    return Response(status_code=204)


@router.get("/bots/{bot_id}/skills", response_model=list[SkillOut])
async def list_skills(bot_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[SkillOut]:
    rows = await skills.list_skills(session, user.id, bot_id)
    return [SkillOut.model_validate(row) for row in rows]


@router.post("/bots/{bot_id}/skills", response_model=SkillOut, status_code=201)
async def create_skill(
    bot_id: uuid.UUID, body: SkillCreate, user: CurrentUser, session: SessionDep
) -> SkillOut:
    return SkillOut.model_validate(await skills.create_skill(session, user.id, bot_id, body))


@router.patch("/skills/{skill_id}", response_model=SkillOut)
async def update_skill(
    skill_id: uuid.UUID, body: SkillUpdate, user: CurrentUser, session: SessionDep
) -> SkillOut:
    return SkillOut.model_validate(await skills.update_skill(session, user.id, skill_id, body))


@router.delete("/skills/{skill_id}", status_code=204)
async def delete_skill(skill_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    await skills.delete_skill(session, user.id, skill_id)
    return Response(status_code=204)
