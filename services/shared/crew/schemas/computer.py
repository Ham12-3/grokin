"""Response model for the user's computer."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class ComputerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: Literal["starting", "running", "paused", "stopped", "error"]
    provider: str
    last_active_at: datetime | None
