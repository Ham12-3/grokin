"""Vault items: list (never values), add, delete, and reading one for a tool call.

Every query filters by `user_id`. Values leave this module only through `reveal`, which
the tool layer calls at the last moment (see `crew.vault.inject`).
"""

import re
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from crew import audit
from crew.errors import AppError
from crew.models import VaultItem
from crew.vault.crypto import KeyWrapper, Sealed, VaultError, seal, unseal

NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
TYPES = ("login", "api_key", "card", "note", "oauth_token")
MAX_ITEMS = 200


def not_found() -> AppError:
    return AppError(404, "vault_item_not_found", "That Vault item does not exist.")


async def list_items(session: AsyncSession, user_id: uuid.UUID) -> list[VaultItem]:
    rows = await session.scalars(
        select(VaultItem).where(VaultItem.user_id == user_id).order_by(VaultItem.name)
    )
    return list(rows.all())


async def add_item(
    session: AsyncSession,
    wrapper: KeyWrapper,
    user_id: uuid.UUID,
    *,
    name: str,
    item_type: str,
    value: str,
) -> VaultItem:
    if not NAME.fullmatch(name):
        raise AppError(
            422,
            "invalid_name",
            "Use 2 to 40 lowercase letters, numbers and underscores, starting with a letter.",
        )
    if len(await list_items(session, user_id)) >= MAX_ITEMS:
        raise AppError(409, "vault_full", "The Vault is full. Delete an item first.")
    sealed = seal(wrapper, user_id, name, value)
    item = VaultItem(
        user_id=user_id,
        name=name,
        type=item_type,
        ciphertext=sealed.ciphertext,
        nonce=sealed.nonce,
        wrapped_data_key=sealed.wrapped_data_key,
        wrapped_by=sealed.wrapped_by,
    )
    session.add(item)
    audit.record(session, user_id=user_id, actor="user", action="vault.add", detail={"name": name})
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise AppError(
            409, "name_taken", "You already have an item with that name. Delete it first."
        ) from error
    await session.refresh(item)
    return item


async def delete_item(session: AsyncSession, user_id: uuid.UUID, item_id: uuid.UUID) -> None:
    item = await session.scalar(
        select(VaultItem).where(VaultItem.id == item_id, VaultItem.user_id == user_id)
    )
    if item is None:
        raise not_found()
    audit.record(
        session, user_id=user_id, actor="user", action="vault.delete", detail={"name": item.name}
    )
    await session.delete(item)
    await session.commit()


async def reveal(
    session: AsyncSession, wrapper: KeyWrapper, user_id: uuid.UUID, name: str
) -> str | None:
    """The decrypted value of this user's item, or None if they have no such item."""
    item = await session.scalar(
        select(VaultItem).where(VaultItem.user_id == user_id, VaultItem.name == name)
    )
    if item is None:
        return None
    sealed = Sealed(item.ciphertext, item.nonce, item.wrapped_data_key, item.wrapped_by)
    return unseal(wrapper, user_id, name, sealed)


__all__ = ["VaultError", "add_item", "delete_item", "list_items", "reveal"]
