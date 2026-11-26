"""Request and response models for connectors and per-Bot app access."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class McpToolOut(BaseModel):
    name: str
    description: str
    safe: bool  # false: every call asks for approval


class ConnectorOut(BaseModel):
    id: uuid.UUID
    kind: str
    name: str
    status: Literal["connected", "pending", "error"]
    # Custom MCP servers only.
    url: str | None = None
    tools: list[McpToolOut] = Field(default_factory=list)


class AvailableApp(BaseModel):
    kind: str
    name: str


class ConnectorList(BaseModel):
    available: list[AvailableApp]
    connected: list[ConnectorOut]
    # False when no connector service is set up on this server (apps cannot be connected).
    configured: bool


class ConnectStarted(BaseModel):
    connector: ConnectorOut
    # The page to open in the browser to finish connecting, if there is one.
    url: str | None


class McpCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=8, max_length=2000)
    # Name of a Vault item holding the request headers, as JSON: {"Authorization": "Bearer ..."}
    headers_secret_ref: str | None = Field(default=None, max_length=40)


class ConnectorUpdate(BaseModel):
    # MCP tools the user marked safe: these run without asking.
    safe_tools: list[str] = Field(max_length=200)


class BotApps(BaseModel):
    connector_ids: list[uuid.UUID] = Field(max_length=50)


class McpToolsRaw(BaseModel):
    tools: list[dict[str, Any]]
