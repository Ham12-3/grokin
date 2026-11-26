"""The Library: things Bots made for the user to keep. Every query filters by `user_id`.

Downloads use a signed address that works for a few minutes and needs no sign-in, so the
app can show a preview or save the file. The signature covers the item and the expiry.
"""

import hashlib
import hmac
import mimetypes
import time
import uuid
from typing import Any

import structlog
from redis.asyncio import Redis
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from crew import events
from crew.config import Settings
from crew.errors import AppError
from crew.library.storage import Storage, StorageError, make_key
from crew.models import LibraryItem, Message
from crew.schemas.chat import MessageOut

log = structlog.get_logger(__name__)

MAX_FILE_BYTES = 20_000_000
MAX_ITEMS = 2000
URL_SECONDS = 300
CATEGORIES = ("document", "image", "pdf", "other")
TEXT_SUFFIXES = (".md", ".txt", ".csv", ".json", ".log", ".yaml", ".yml", ".html", ".xml", ".py")


def not_found() -> AppError:
    return AppError(404, "library_item_not_found", "That item is not in your Library.")


def guess_mime(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".md"):
        return "text/markdown"
    if lowered.endswith(TEXT_SUFFIXES):
        return mimetypes.guess_type(lowered)[0] or "text/plain"
    return mimetypes.guess_type(lowered)[0] or "application/octet-stream"


def category(mime: str | None) -> str:
    kind = mime or ""
    if kind.startswith("image/"):
        return "image"
    if kind == "application/pdf":
        return "pdf"
    if kind.startswith("text/") or kind in ("application/json", "application/xml"):
        return "document"
    return "other"


def _signature(settings: Settings, item_id: uuid.UUID, expires: int) -> str:
    secret = (settings.jwt_secret or "").encode()
    return hmac.new(secret, f"library:{item_id}:{expires}".encode(), hashlib.sha256).hexdigest()


def download_url(settings: Settings, item_id: uuid.UUID) -> str:
    expires = int(time.time()) + URL_SECONDS
    base = settings.api_base_url.rstrip("/")
    sig = _signature(settings, item_id, expires)
    return f"{base}/api/v1/library/{item_id}/content?expires={expires}&sig={sig}"


def check_signature(settings: Settings, item_id: uuid.UUID, expires: int, sig: str) -> bool:
    expected = _signature(settings, item_id, expires)
    return hmac.compare_digest(expected, sig) and expires >= int(time.time())


async def list_items(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    q: str | None = None,
    bot_id: uuid.UUID | None = None,
    kind: str | None = None,
    item_category: str | None = None,
) -> list[LibraryItem]:
    query = select(LibraryItem).where(LibraryItem.user_id == user_id)
    if bot_id is not None:
        query = query.where(LibraryItem.bot_id == bot_id)
    if kind:
        query = query.where(LibraryItem.kind == kind)
    if q and q.strip():
        # Plain "contains" search; % and _ in what the user typed are not wildcards.
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{needle}%"
        query = query.where(or_(LibraryItem.title.ilike(pattern), LibraryItem.path.ilike(pattern)))
    rows = (await session.scalars(query.order_by(LibraryItem.id.desc()).limit(500))).all()
    if item_category:
        return [row for row in rows if category(row.mime) == item_category]
    return list(rows)


async def load(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> LibraryItem:
    item = await session.scalar(
        select(LibraryItem).where(LibraryItem.id == item_id, LibraryItem.user_id == user_id)
    )
    if item is None:
        raise not_found()
    return item


async def add_file(
    session: AsyncSession,
    storage: Storage,
    *,
    user_id: uuid.UUID,
    bot_id: uuid.UUID | None,
    run_id: uuid.UUID | None,
    path: str,
    title: str,
    data: bytes,
) -> LibraryItem:
    """Stores a copy and records it. The same path replaces the earlier copy."""
    if len(data) > MAX_FILE_BYTES:
        raise AppError(413, "file_too_large", "That file is too large for the Library.")
    filename = path.rsplit("/", 1)[-1] or "file"
    mime = guess_mime(filename)
    existing = await session.scalar(
        select(LibraryItem).where(LibraryItem.user_id == user_id, LibraryItem.path == path)
    )
    item = existing or LibraryItem(user_id=user_id, kind="file", title="", path=path)
    if existing is None:
        session.add(item)
        await session.flush()
    key = make_key(user_id, item.id, filename)
    try:
        await storage.put(key, data, mime)
    except StorageError as error:
        await session.rollback()
        raise AppError(502, "storage_failed", str(error)) from error
    item.title = (title.strip() or filename)[:200]
    item.bot_id, item.run_id = bot_id, run_id
    item.storage_key, item.mime, item.size_bytes = key, mime, len(data)
    await session.commit()
    await session.refresh(item)
    return item


async def read(session: AsyncSession, storage: Storage, item: LibraryItem) -> bytes:
    if not item.storage_key:
        raise not_found()
    try:
        return await storage.get(item.storage_key)
    except StorageError as error:
        raise AppError(404, "file_missing", str(error)) from error


async def delete_item(
    session: AsyncSession, storage: Storage, user_id: uuid.UUID, item_id: uuid.UUID
) -> None:
    item = await load(session, user_id, item_id)
    if item.storage_key:
        try:
            await storage.delete(item.storage_key)
        except StorageError:
            pass
    await session.delete(item)
    await session.commit()


def card(item: LibraryItem) -> dict[str, Any]:
    """The file card shown in a chat. It links to the Library item."""
    return {
        "type": "file",
        "library_id": str(item.id),
        "title": item.title,
        "mime": item.mime,
        "size_bytes": item.size_bytes,
    }


async def post_file_card(
    session: AsyncSession, redis: Redis, chat_id: uuid.UUID, bot_id: uuid.UUID, item: LibraryItem
) -> None:
    message = Message(
        chat_id=chat_id, role="system", bot_id=bot_id, content=item.title, card=card(item)
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    await events.publish(
        redis,
        events.chat_channel(chat_id),
        "message.created",
        {
            "chat_id": str(chat_id),
            "message": MessageOut.model_validate(message).model_dump(mode="json"),
        },
    )
