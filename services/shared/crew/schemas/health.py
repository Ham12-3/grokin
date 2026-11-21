"""Response model for the health endpoint."""

from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["ok", "error"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    db: CheckStatus
    redis: CheckStatus
