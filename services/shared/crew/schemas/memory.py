"""Request and response models for memory lines and skills."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _strip(value: str) -> str:
    return value.strip()


class MemoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    text: str
    created_at: datetime


class MemoryWrite(BaseModel):
    text: str = Field(min_length=1, max_length=300)

    @field_validator("text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("the line is empty")
        return value


class SkillOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bot_id: uuid.UUID
    slug: str
    name: str
    description: str
    steps: str
    rules: str
    created_at: datetime


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=300)
    steps: str = Field(min_length=1, max_length=20_000)
    rules: str = Field(default="", max_length=5000)

    _clean = field_validator("name", "description")(_strip)

    @field_validator("name", "steps")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class SkillUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    steps: str | None = Field(default=None, min_length=1, max_length=20_000)
    rules: str | None = Field(default=None, max_length=5000)

    @field_validator("name", "steps")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be empty")
        return value
