"""Vault routes. Logic lives in `crew.vault.service`. No route returns a value."""

import uuid

from fastapi import APIRouter, Request, Response

from api.deps import CurrentUser, SessionDep
from crew.errors import AppError
from crew.schemas.vault import VaultItemCreate, VaultItemOut
from crew.vault import service
from crew.vault.crypto import KeyWrapper

router = APIRouter(prefix="/vault", tags=["vault"])


def _wrapper(request: Request) -> KeyWrapper:
    wrapper: KeyWrapper | None = request.app.state.vault
    if wrapper is None:
        raise AppError(503, "vault_not_configured", "The Vault is not set up on this server.")
    return wrapper


@router.get("", response_model=list[VaultItemOut])
async def list_items(user: CurrentUser, session: SessionDep) -> list[VaultItemOut]:
    return [
        VaultItemOut.model_validate(item) for item in await service.list_items(session, user.id)
    ]


@router.post("", response_model=VaultItemOut, status_code=201)
async def add_item(
    body: VaultItemCreate, request: Request, user: CurrentUser, session: SessionDep
) -> VaultItemOut:
    item = await service.add_item(
        session, _wrapper(request), user.id, name=body.name, item_type=body.type, value=body.value
    )
    return VaultItemOut.model_validate(item)


@router.delete("/{item_id}", status_code=204)
async def delete_item(item_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    await service.delete_item(session, user.id, item_id)
    return Response(status_code=204)
