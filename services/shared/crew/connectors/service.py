"""Connectors: connect and disconnect apps, add custom MCP servers, per-Bot app access.

Every query filters by `user_id`. App tokens live with the connector backend (Composio);
MCP headers live in the Vault. Nothing secret is stored in `connectors`.
"""

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crew import audit
from crew.config import Settings
from crew.connectors import mcp_client
from crew.connectors.backend import KINDS, ConnectorBackend, ConnectorError
from crew.connectors.mcp_client import Opener, open_http
from crew.errors import AppError
from crew.models import Bot, Connector, VaultItem
from crew.schemas.connector import (
    AvailableApp,
    ConnectorList,
    ConnectorOut,
    ConnectStarted,
    McpCreate,
    McpToolOut,
)
from crew.tools.net import Resolver, check_url, system_resolver
from crew.tools.registry import ToolError
from crew.vault import service as vault
from crew.vault.crypto import KeyWrapper, VaultError

MAX_CONNECTORS = 30


def not_found() -> AppError:
    return AppError(404, "connector_not_found", "That app is not connected.")


def _unavailable() -> AppError:
    return AppError(
        503, "connectors_not_configured", "Apps cannot be connected on this server yet."
    )


def out(connector: Connector) -> ConnectorOut:
    config = connector.config or {}
    safe = set(config.get("safe_tools", []))
    return ConnectorOut(
        id=connector.id,
        kind=connector.kind,
        name=connector.name,
        status=connector.status,
        url=config.get("url") if connector.kind == "mcp" else None,
        tools=[
            McpToolOut(
                name=str(tool["name"]),
                description=str(tool.get("description", "")),
                safe=tool["name"] in safe,
            )
            for tool in config.get("tools", [])
        ],
    )


async def _all(session: AsyncSession, user_id: uuid.UUID) -> list[Connector]:
    rows = await session.scalars(
        select(Connector).where(Connector.user_id == user_id).order_by(Connector.id)
    )
    return list(rows.all())


async def load(session: AsyncSession, user_id: uuid.UUID, connector_id: uuid.UUID) -> Connector:
    connector = await session.scalar(
        select(Connector).where(Connector.id == connector_id, Connector.user_id == user_id)
    )
    if connector is None:
        raise not_found()
    return connector


async def list_connectors(
    session: AsyncSession, backend: ConnectorBackend | None, user_id: uuid.UUID
) -> ConnectorList:
    connectors = await _all(session, user_id)
    # A connection the user is finishing in the browser: ask the backend how it went.
    changed = False
    for connector in connectors:
        if connector.status == "pending" and backend is not None:
            try:
                status = await backend.status(str(connector.config.get("connection_id", "")))
            except ConnectorError:
                status = "pending"
            if status != connector.status:
                connector.status = status
                changed = True
    if changed:
        await session.commit()
    return ConnectorList(
        available=[AvailableApp(kind=kind, name=name) for kind, name in KINDS.items()],
        connected=[out(connector) for connector in connectors],
        configured=backend is not None,
    )


async def connect(
    session: AsyncSession, backend: ConnectorBackend | None, user_id: uuid.UUID, kind: str
) -> ConnectStarted:
    if kind not in KINDS:
        raise AppError(404, "unknown_app", "That app is not supported.")
    if backend is None:
        raise _unavailable()
    existing = [item for item in await _all(session, user_id) if item.kind == kind]
    for connector in existing:
        if connector.status == "connected":
            raise AppError(409, "already_connected", f"{KINDS[kind]} is already connected.")
        await session.delete(connector)  # an attempt that was never finished
    try:
        connection_id, url = await backend.connect(user_id, kind)
    except ConnectorError as error:
        raise AppError(502, "connect_failed", str(error)) from error
    connector = Connector(
        user_id=user_id,
        kind=kind,
        name=KINDS[kind],
        config={"connection_id": connection_id},
        status="pending" if url else "connected",
    )
    session.add(connector)
    await session.flush()
    audit.record(
        session,
        user_id=user_id,
        actor="user",
        action="connector.connect",
        target=str(connector.id),
        detail={"kind": kind},
    )
    await session.commit()
    await session.refresh(connector)
    return ConnectStarted(connector=out(connector), url=url)


async def mcp_headers(
    session: AsyncSession, wrapper: KeyWrapper | None, connector: Connector
) -> dict[str, str]:
    """The request headers for an MCP server, read from the Vault now."""
    if connector.secret_id is None:
        return {}
    item = await session.get(VaultItem, connector.secret_id)
    if item is None or item.user_id != connector.user_id or wrapper is None:
        raise ConnectorError("The Vault item with this server's headers is missing.")
    try:
        value = await vault.reveal(session, wrapper, connector.user_id, item.name)
        parsed = json.loads(value or "")
    except (VaultError, ValueError) as error:
        raise ConnectorError(
            'The Vault item for this server must be JSON, like {"Authorization": "Bearer ..."}.'
        ) from error
    if not isinstance(parsed, dict) or not all(isinstance(v, str) for v in parsed.values()):
        raise ConnectorError("The Vault item for this server must be a JSON object of text.")
    return {str(key): str(value) for key, value in parsed.items()}


async def _check_mcp_url(settings: Settings, url: str, resolver: Resolver) -> None:
    if settings.mcp_allow_private:
        return  # development: a server on this machine
    if not url.lower().startswith("https://"):
        raise AppError(422, "invalid_url", "The MCP address must start with https://.")
    try:
        await check_url(url, resolver)
    except ToolError as error:
        raise AppError(422, "invalid_url", str(error)) from error


async def add_mcp(
    session: AsyncSession,
    settings: Settings,
    wrapper: KeyWrapper | None,
    user_id: uuid.UUID,
    body: McpCreate,
    *,
    opener: Opener = open_http,
    resolver: Resolver = system_resolver,
) -> ConnectorOut:
    if len(await _all(session, user_id)) >= MAX_CONNECTORS:
        raise AppError(409, "too_many_connectors", "Disconnect an app first.")
    url = body.url.strip()
    await _check_mcp_url(settings, url, resolver)
    secret_id: uuid.UUID | None = None
    if body.headers_secret_ref:
        secret_id = await session.scalar(
            select(VaultItem.id).where(
                VaultItem.user_id == user_id, VaultItem.name == body.headers_secret_ref
            )
        )
        if secret_id is None:
            raise AppError(404, "vault_item_not_found", "That Vault item does not exist.")
    connector = Connector(
        user_id=user_id,
        kind="mcp",
        name=body.name.strip(),
        config={"url": url, "tools": [], "safe_tools": []},
        secret_id=secret_id,
    )
    try:
        headers = await mcp_headers(session, wrapper, connector)
        tools = await mcp_client.list_tools(url, headers, opener)
    except ConnectorError as error:
        raise AppError(502, "mcp_unreachable", str(error)) from error
    connector.config = {"url": url, "tools": tools, "safe_tools": []}
    session.add(connector)
    await session.flush()
    audit.record(
        session,
        user_id=user_id,
        actor="user",
        action="connector.connect",
        target=str(connector.id),
        detail={"kind": "mcp"},
    )
    await session.commit()
    await session.refresh(connector)
    return out(connector)


async def set_safe_tools(
    session: AsyncSession, user_id: uuid.UUID, connector_id: uuid.UUID, safe_tools: list[str]
) -> ConnectorOut:
    connector = await load(session, user_id, connector_id)
    if connector.kind != "mcp":
        raise AppError(422, "not_mcp", "Only custom MCP servers have tool settings.")
    known = {str(tool["name"]) for tool in connector.config.get("tools", [])}
    connector.config = {
        **connector.config,
        "safe_tools": sorted(name for name in set(safe_tools) if name in known),
    }
    await session.commit()
    await session.refresh(connector)
    return out(connector)


async def disconnect(
    session: AsyncSession,
    backend: ConnectorBackend | None,
    user_id: uuid.UUID,
    connector_id: uuid.UUID,
) -> None:
    connector = await load(session, user_id, connector_id)
    if connector.kind != "mcp" and backend is not None:
        try:
            await backend.disconnect(str(connector.config.get("connection_id", "")))
        except ConnectorError:
            pass  # gone on their side already, or unreachable: still remove it here
    # No Bot keeps access to something that is gone.
    bots = (await session.scalars(select(Bot).where(Bot.user_id == user_id))).all()
    for bot in bots:
        if connector.id in bot.apps:
            bot.apps = [app for app in bot.apps if app != connector.id]
    audit.record(
        session,
        user_id=user_id,
        actor="user",
        action="connector.disconnect",
        target=str(connector.id),
        detail={"kind": connector.kind},
    )
    await session.delete(connector)
    await session.commit()


# --- Per-Bot access ---------------------------------------------------------------------


async def get_bot_apps(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID
) -> list[uuid.UUID]:
    bot = await session.scalar(select(Bot).where(Bot.id == bot_id, Bot.user_id == user_id))
    if bot is None:
        raise AppError(404, "bot_not_found", "That Bot does not exist.")
    return list(bot.apps)


async def set_bot_apps(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID, connector_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    bot = await session.scalar(select(Bot).where(Bot.id == bot_id, Bot.user_id == user_id))
    if bot is None:
        raise AppError(404, "bot_not_found", "That Bot does not exist.")
    owned = {connector.id for connector in await _all(session, user_id)}
    if not set(connector_ids) <= owned:
        raise not_found()
    bot.apps = sorted(set(connector_ids))
    await session.commit()
    return list(bot.apps)


async def for_bot(session: AsyncSession, bot: Bot) -> list[Connector]:
    """The connected apps this Bot is allowed to use."""
    if not bot.apps:
        return []
    rows = await session.scalars(
        select(Connector).where(
            Connector.user_id == bot.user_id,
            Connector.id.in_(bot.apps),
            Connector.status == "connected",
        )
    )
    return list(rows.all())


def describe(connectors: list[Connector]) -> list[dict[str, Any]]:
    return [{"kind": connector.kind, "name": connector.name} for connector in connectors]
