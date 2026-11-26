"""`{{vault:name}}` placeholders: the only way a secret reaches a tool.

The model writes the placeholder. Just before a tool runs, the tool layer swaps in the
real value (`resolve`), and everything that comes back is scrubbed (`redact`) before it is
stored, logged or shown to the model. The model never sees a value.
"""

import re
import uuid
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from crew import audit
from crew.vault import service
from crew.vault.crypto import KeyWrapper, VaultError

PLACEHOLDER = re.compile(r"\{\{\s*vault:([a-z][a-z0-9_]{1,39})\s*\}\}")
REDACTED = "[redacted]"
# Too-short values would turn ordinary text into [redacted] soup.
MIN_REDACT_CHARS = 4

# Secret values in use by the run on this task, for the log scrubber.
_active: ContextVar[frozenset[str]] = ContextVar("vault_active_secrets", default=frozenset())


class MissingSecret(Exception):
    """The arguments name a Vault item the user does not have. Safe to show."""


def names_in(value: Any) -> set[str]:
    """Every Vault item named anywhere inside a tool's arguments."""
    if isinstance(value, str):
        return set(PLACEHOLDER.findall(value))
    if isinstance(value, dict):
        return set().union(*(names_in(item) for item in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(names_in(item) for item in value)) if value else set()
    return set()


def _swap(value: Any, secrets: dict[str, str]) -> Any:
    if isinstance(value, str):
        return PLACEHOLDER.sub(lambda match: secrets[match.group(1)], value)
    if isinstance(value, dict):
        return {key: _swap(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [_swap(item, secrets) for item in value]
    return value


async def resolve(
    session: AsyncSession,
    wrapper: KeyWrapper | None,
    user_id: uuid.UUID,
    args: dict[str, Any],
    *,
    tool: str,
) -> tuple[dict[str, Any], list[str]]:
    """Returns the arguments with real values, and those values (to scrub the result)."""
    names = names_in(args)
    if not names:
        return args, []
    if wrapper is None:
        raise MissingSecret("The Vault is not set up on this server.")
    secrets: dict[str, str] = {}
    for name in sorted(names):
        try:
            value = await service.reveal(session, wrapper, user_id, name)
        except VaultError as error:
            raise MissingSecret(str(error)) from error
        if value is None:
            raise MissingSecret(f"There is no Vault item named {name}.")
        secrets[name] = value
    audit.record(
        session,
        user_id=user_id,
        actor="bot",
        action="vault.use",
        detail={"names": sorted(names), "tool": tool},
    )
    await session.commit()
    values = list(secrets.values())
    _active.set(_active.get() | frozenset(values))
    return _swap(args, secrets), values


def redact(text: str, values: list[str] | frozenset[str]) -> str:
    """Replaces every secret value found in `text`."""
    for value in sorted(values, key=len, reverse=True):
        if len(value) >= MIN_REDACT_CHARS:
            text = text.replace(value, REDACTED)
    return text


def _scrub(value: Any, values: frozenset[str]) -> Any:
    if isinstance(value, str):
        return redact(value, values)
    if isinstance(value, dict):
        return {key: _scrub(item, values) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_scrub(item, values) for item in value]
    return value


def redact_log_event(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """structlog processor: no secret in use by this run reaches a log line."""
    values = _active.get()
    if not values:
        return event
    scrubbed: dict[str, Any] = _scrub(dict(event), values)
    return scrubbed


def forget_active() -> None:
    """Called when a run ends."""
    _active.set(frozenset())
