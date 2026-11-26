"""Library routes. Logic lives in `crew.library.service`."""

import uuid
from typing import Literal

from fastapi import APIRouter, Request, Response

from api.deps import CurrentUser, SessionDep, SettingsDep
from crew.library import service
from crew.models import LibraryItem
from crew.schemas.library import LibraryItemDetail, LibraryItemOut

router = APIRouter(prefix="/library", tags=["library"])


def _fields(item: LibraryItem) -> dict[str, object]:
    return {
        "id": item.id,
        "bot_id": item.bot_id,
        "run_id": item.run_id,
        "kind": item.kind,
        "category": service.category(item.mime),
        "title": item.title,
        "path": item.path,
        "mime": item.mime,
        "size_bytes": item.size_bytes,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


@router.get("", response_model=list[LibraryItemOut])
async def list_items(
    user: CurrentUser,
    session: SessionDep,
    q: str | None = None,
    bot_id: uuid.UUID | None = None,
    type: Literal["file", "page", "result"] | None = None,
    category: Literal["document", "image", "pdf", "other"] | None = None,
) -> list[LibraryItemOut]:
    rows = await service.list_items(
        session, user.id, q=q, bot_id=bot_id, kind=type, item_category=category
    )
    return [LibraryItemOut.model_validate(_fields(row)) for row in rows]


@router.get("/{item_id}", response_model=LibraryItemDetail)
async def get_item(
    item_id: uuid.UUID, user: CurrentUser, session: SessionDep, settings: SettingsDep
) -> LibraryItemDetail:
    item = await service.load(session, user.id, item_id)
    return LibraryItemDetail.model_validate(
        {**_fields(item), "download_url": service.download_url(settings, item.id)}
    )


@router.delete("/{item_id}", status_code=204)
async def delete_item(
    item_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep
) -> Response:
    await service.delete_item(session, request.app.state.storage, user.id, item_id)
    return Response(status_code=204)


@router.get("/{item_id}/content")
async def content(
    item_id: uuid.UUID,
    expires: int,
    sig: str,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
) -> Response:
    """The file itself. No sign-in: the signature (made for its owner) is the key."""
    if not service.check_signature(settings, item_id, expires, sig):
        raise service.not_found()
    item = await session.get(LibraryItem, item_id)
    if item is None:
        raise service.not_found()
    data = await service.read(session, request.app.state.storage, item)
    mime = item.mime or "application/octet-stream"
    # A Bot may have written anything: never let a browser run it as a page or a script.
    if service.category(mime) == "document" or mime.endswith(("html", "xml", "javascript")):
        mime = "text/plain; charset=utf-8"
    filename = (item.path or "file").rsplit("/", 1)[-1].replace('"', "")
    return Response(
        data,
        media_type=mime,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
            "Cache-Control": "private, no-store",
        },
    )
