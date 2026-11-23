"""Sign-in flows. Routes call these; nothing here knows about HTTP requests.

Short-lived values live in Redis under a sha256 of the secret, never the secret itself:
  auth:magic:<hash>   email + PKCE challenge, single use
  auth:code:<hash>    user id + PKCE challenge, 60 seconds, single use
  auth:gstate:<hash>  PKCE challenge for a Google round trip, single use
"""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx
from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from crew import audit
from crew.auth import google
from crew.auth.mailer import Mailer
from crew.auth.tokens import (
    REFRESH_TOKEN_BYTES,
    create_access_token,
    new_token,
    sha256_hex,
    verify_pkce,
)
from crew.config import Settings
from crew.errors import AppError, unauthorized
from crew.models import RefreshToken, User

EMAIL_WINDOW_SECONDS = 15 * 60


@dataclass(frozen=True)
class IssuedTokens:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str


def _invalid_code() -> AppError:
    return AppError(400, "invalid_code", "This sign-in code is invalid or has expired.")


def _invalid_link() -> AppError:
    return AppError(400, "invalid_link", "This sign-in link is invalid or has expired.")


def _check_redirect(settings: Settings, redirect: str) -> None:
    """Only the desktop deep link is allowed, so the API can never be an open redirect."""
    if redirect != settings.desktop_deep_link:
        raise AppError(400, "invalid_redirect", "Unknown redirect target.")


async def _put(redis: Redis, key: str, value: dict[str, str], ttl_seconds: int) -> None:
    await redis.set(key, json.dumps(value), ex=ttl_seconds)


async def _take(redis: Redis, key: str) -> dict[str, str] | None:
    """Reads and deletes in one step, so a value can be used only once."""
    raw = await redis.getdel(key)
    if raw is None:
        return None
    loaded: dict[str, str] = json.loads(raw)
    return loaded


# --- Email magic link -------------------------------------------------------------------


async def start_email_login(
    redis: Redis, settings: Settings, mailer: Mailer, *, email: str, code_challenge: str
) -> None:
    email = email.strip().lower()
    limit_key = f"auth:rl:email:{sha256_hex(email)}"
    attempts = await redis.incr(limit_key)
    if attempts == 1:
        await redis.expire(limit_key, EMAIL_WINDOW_SECONDS)
    if attempts > settings.email_login_max_per_window:
        raise AppError(429, "too_many_requests", "Too many sign-in emails. Try again later.")

    token = new_token()
    await _put(
        redis,
        f"auth:magic:{sha256_hex(token)}",
        {"email": email, "code_challenge": code_challenge},
        settings.magic_link_minutes * 60,
    )
    link = f"{settings.api_base_url}{settings.api_prefix}/auth/callback?token={token}"
    await mailer.send_magic_link(email, link)


async def complete_email_login(
    session: AsyncSession, redis: Redis, settings: Settings, *, token: str
) -> str:
    """Checks the magic link and returns a one-time code for the desktop app."""
    data = await _take(redis, f"auth:magic:{sha256_hex(token)}")
    if data is None:
        raise _invalid_link()
    user = await _upsert_user(session, settings, email=data["email"], name=None, avatar_url=None)
    await session.commit()
    return await _issue_login_code(redis, settings, user.id, data["code_challenge"], "email")


# --- Google -----------------------------------------------------------------------------


async def start_google_login(
    redis: Redis, settings: Settings, *, redirect: str, code_challenge: str
) -> str:
    """Returns the Google URL to send the browser to."""
    google.require_google(settings)
    _check_redirect(settings, redirect)
    state = new_token()
    await _put(
        redis,
        f"auth:gstate:{sha256_hex(state)}",
        {"code_challenge": code_challenge},
        settings.oauth_state_minutes * 60,
    )
    return google.authorize_url(settings, state)


async def complete_google_login(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    http: httpx.AsyncClient,
    *,
    code: str,
    state: str,
) -> str:
    google.require_google(settings)
    data = await _take(redis, f"auth:gstate:{sha256_hex(state)}")
    if data is None:
        raise _invalid_link()
    profile = await google.fetch_profile(http, settings, code)
    user = await _upsert_user(
        session, settings, email=profile.email, name=profile.name, avatar_url=profile.avatar_url
    )
    await session.commit()
    return await _issue_login_code(redis, settings, user.id, data["code_challenge"], "google")


# --- One-time code -> tokens ------------------------------------------------------------


async def _issue_login_code(
    redis: Redis, settings: Settings, user_id: uuid.UUID, code_challenge: str, provider: str
) -> str:
    code = new_token()
    await _put(
        redis,
        f"auth:code:{sha256_hex(code)}",
        {"user_id": str(user_id), "code_challenge": code_challenge, "provider": provider},
        settings.auth_code_seconds,
    )
    return code


async def exchange_code(
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
    *,
    code: str,
    code_verifier: str,
    device_id: uuid.UUID | None,
    device_name: str | None,
) -> IssuedTokens:
    data = await _take(redis, f"auth:code:{sha256_hex(code)}")
    if data is None:
        raise _invalid_code()
    if not verify_pkce(code_verifier, data["code_challenge"]):
        raise _invalid_code()
    user = await session.get(User, uuid.UUID(data["user_id"]))
    if user is None:
        raise _invalid_code()

    refresh_token = _add_refresh_token(session, settings, user.id, device_id, device_name)
    audit.record(
        session,
        user_id=user.id,
        actor="user",
        action="login",
        detail={"provider": data.get("provider"), "device_name": device_name},
    )
    await session.commit()
    access_token, expires_in = create_access_token(user.id, settings)
    return IssuedTokens(user, access_token, expires_in, refresh_token)


async def refresh_tokens(
    session: AsyncSession, settings: Settings, *, refresh_token: str
) -> IssuedTokens:
    """Rotates the refresh token. A reused (already rotated) token signs that device out."""
    invalid = unauthorized("invalid_refresh_token", "Your session has ended. Sign in again.")
    row = await session.scalar(
        select(RefreshToken)
        .where(RefreshToken.token_hash == sha256_hex(refresh_token))
        .with_for_update()
    )
    if row is None:
        raise invalid
    now = datetime.now(UTC)
    if row.revoked_at is not None:
        # Someone is replaying an old token: revoke every live token for this device.
        await _revoke_device(session, row.user_id, row.device_id, now)
        audit.record(session, user_id=row.user_id, actor="system", action="refresh_token_reuse")
        await session.commit()
        raise invalid
    if row.expires_at <= now:
        raise invalid
    user = await session.get(User, row.user_id)
    if user is None:
        raise invalid

    row.revoked_at = now
    new_refresh = _add_refresh_token(session, settings, user.id, row.device_id, row.device_name)
    await session.commit()
    access_token, expires_in = create_access_token(user.id, settings)
    return IssuedTokens(user, access_token, expires_in, new_refresh)


async def logout(session: AsyncSession, *, refresh_token: str) -> None:
    """Revokes the token. Unknown tokens are ignored so logout always succeeds."""
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == sha256_hex(refresh_token))
    )
    if row is None:
        return
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
    audit.record(session, user_id=row.user_id, actor="user", action="logout")
    await session.commit()


# --- Helpers ----------------------------------------------------------------------------


def _add_refresh_token(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    device_id: uuid.UUID | None,
    device_name: str | None,
) -> str:
    raw = new_token(REFRESH_TOKEN_BYTES)
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=sha256_hex(raw),
            device_id=device_id,
            device_name=device_name,
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    return raw


async def _revoke_device(
    session: AsyncSession, user_id: uuid.UUID, device_id: uuid.UUID | None, now: datetime
) -> None:
    if device_id is None:
        return
    await session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.device_id == device_id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )


async def _upsert_user(
    session: AsyncSession,
    settings: Settings,
    *,
    email: str,
    name: str | None,
    avatar_url: str | None,
) -> User:
    """Creates the user on first sign-in. Safe if two sign-ins race."""
    await session.execute(
        insert(User)
        .values(
            email=email,
            name=name,
            avatar_url=avatar_url,
            daily_token_budget=settings.crew_daily_token_budget,
        )
        .on_conflict_do_nothing(index_elements=[User.email])
    )
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:  # pragma: no cover - the insert above guarantees a row
        raise RuntimeError("user upsert failed")
    if name and not user.name:
        user.name = name
    if avatar_url and not user.avatar_url:
        user.avatar_url = avatar_url
    return user
