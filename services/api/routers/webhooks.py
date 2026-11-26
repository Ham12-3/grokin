"""Public webhooks. No sign-in: the secret in the URL is the key."""

import uuid

from fastapi import APIRouter

from api.deps import QueueDep, RedisDep, SessionDep, SettingsDep
from crew.routines import service
from crew.schemas.run import CancelResponse

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/routines/{routine_id}/{secret}", response_model=CancelResponse, status_code=202)
async def routine_webhook(
    routine_id: uuid.UUID,
    secret: str,
    session: SessionDep,
    redis: RedisDep,
    queue: QueueDep,
    settings: SettingsDep,
) -> CancelResponse:
    """Starts the routine. The request body is ignored: it is never shown to the Bot."""
    run_id = await service.fire_webhook(session, redis, queue, settings, routine_id, secret)
    return CancelResponse(run_id=run_id, status="queued")
