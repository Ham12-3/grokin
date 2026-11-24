"""Request and response models for sign-in."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

# A base64url sha256 is 43 characters; PKCE verifiers are 43 to 128 (RFC 7636).
CodeChallenge = Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
CodeVerifier = Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9._~-]+$")


class EmailStartRequest(BaseModel):
    email: EmailStr
    code_challenge: str = CodeChallenge


class EmailStartResponse(BaseModel):
    status: Literal["sent"] = "sent"


class ExchangeRequest(BaseModel):
    code: str = Field(min_length=1, max_length=256)
    code_verifier: str = CodeVerifier
    device_id: uuid.UUID | None = None
    device_name: str | None = Field(default=None, max_length=120)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=256)


class LogoutRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    name: str | None
    avatar_url: str | None
    timezone: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    user: UserOut


class MeResponse(UserOut):
    daily_token_budget: int
    input_tokens_today: int
    output_tokens_today: int
