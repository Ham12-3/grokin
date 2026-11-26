"""Connector routes. Logic lives in `crew.connectors.service`."""

import uuid

from fastapi import APIRouter, Request, Response

from api.deps import CurrentUser, SessionDep, SettingsDep
from crew.connectors import service
from crew.schemas.connector import (
    BotApps,
    ConnectorList,
    ConnectorOut,
    ConnectorUpdate,
    ConnectStarted,
    McpCreate,
)

router = APIRouter(tags=["connectors"])


@router.get("/connectors", response_model=ConnectorList)
async def list_connectors(
    request: Request, user: CurrentUser, session: SessionDep
) -> ConnectorList:
    return await service.list_connectors(session, request.app.state.connectors, user.id)


@router.post("/connectors/mcp", response_model=ConnectorOut, status_code=201)
async def add_mcp(
    body: McpCreate,
    request: Request,
    user: CurrentUser,
    session: SessionDep,
    settings: SettingsDep,
) -> ConnectorOut:
    state = request.app.state
    return await service.add_mcp(
        session, settings, state.vault, user.id, body, opener=state.mcp_opener
    )


@router.post("/connectors/{kind}/connect", response_model=ConnectStarted)
async def connect(
    kind: str, request: Request, user: CurrentUser, session: SessionDep
) -> ConnectStarted:
    return await service.connect(session, request.app.state.connectors, user.id, kind)


@router.patch("/connectors/{connector_id}", response_model=ConnectorOut)
async def update_connector(
    connector_id: uuid.UUID, body: ConnectorUpdate, user: CurrentUser, session: SessionDep
) -> ConnectorOut:
    return await service.set_safe_tools(session, user.id, connector_id, body.safe_tools)


@router.delete("/connectors/{connector_id}", status_code=204)
async def disconnect(
    connector_id: uuid.UUID, request: Request, user: CurrentUser, session: SessionDep
) -> Response:
    await service.disconnect(session, request.app.state.connectors, user.id, connector_id)
    return Response(status_code=204)


@router.get("/bots/{bot_id}/apps", response_model=BotApps)
async def get_bot_apps(bot_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> BotApps:
    return BotApps(connector_ids=await service.get_bot_apps(session, user.id, bot_id))


@router.put("/bots/{bot_id}/apps", response_model=BotApps)
async def set_bot_apps(
    bot_id: uuid.UUID, body: BotApps, user: CurrentUser, session: SessionDep
) -> BotApps:
    """Which connected apps this Bot may use. A Bot gets no app tools unless listed here."""
    apps = await service.set_bot_apps(session, user.id, bot_id, body.connector_ids)
    return BotApps(connector_ids=apps)
