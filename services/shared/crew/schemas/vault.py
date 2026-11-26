"""Request and response models for the Vault. Values go in and never come out."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

VaultType = Literal["login", "api_key", "card", "note", "oauth_token"]


class VaultItemOut(BaseModel):
    """Name and type only. There is no field for the value."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    type: VaultType
    created_at: datetime


class VaultItemCreate(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    type: VaultType
    value: str = Field(min_length=1, max_length=10_000, repr=False)
