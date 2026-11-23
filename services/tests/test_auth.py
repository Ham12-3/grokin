"""Sign-in end to end against real Postgres and Redis."""

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
from sqlalchemy import text

from crew.auth.tokens import JWT_ALGORITHM, new_token, pkce_challenge, sha256_hex
from tests.conftest import Ctx

API = "/api/v1"
EMAIL = "sam@example.com"


def _pkce() -> tuple[str, str]:
    verifier = new_token(48)
    return verifier, pkce_challenge(verifier)


def _code_from_page(page: str) -> str:
    match = re.search(r'href="crew://auth\?code=([A-Za-z0-9_-]+)"', page)
    assert match, page
    return match.group(1)


async def _email_code(ctx: Ctx, email: str = EMAIL) -> tuple[str, str]:
    """Runs the magic-link steps and returns (one-time code, PKCE verifier)."""
    verifier, challenge = _pkce()
    resp = await ctx.client.post(
        f"{API}/auth/email/start", json={"email": email, "code_challenge": challenge}
    )
    assert resp.status_code == 200, resp.text
    sent_to, link = ctx.mailer.sent[-1]
    assert sent_to == email.lower()
    page = await ctx.client.get(urlsplit(link).path + "?" + urlsplit(link).query)
    assert page.status_code == 200, page.text
    return _code_from_page(page.text), verifier


async def _sign_in(ctx: Ctx, email: str = EMAIL, device_id: str | None = None) -> dict[str, Any]:
    code, verifier = await _email_code(ctx, email)
    body: dict[str, str] = {"code": code, "code_verifier": verifier, "device_name": "test-laptop"}
    if device_id:
        body["device_id"] = device_id
    resp = await ctx.client.post(f"{API}/auth/exchange", json=body)
    assert resp.status_code == 200, resp.text
    tokens: dict[str, Any] = resp.json()
    return tokens


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- Happy path -------------------------------------------------------------------------


async def test_email_sign_in_happy_path(ctx: Ctx) -> None:
    tokens = await _sign_in(ctx)
    assert tokens["token_type"] == "bearer"
    assert tokens["expires_in"] == 15 * 60
    assert tokens["user"]["email"] == EMAIL

    me = await ctx.client.get(f"{API}/me", headers=_bearer(tokens["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL
    assert me.json()["daily_token_budget"] == ctx.settings.crew_daily_token_budget


async def test_callback_page_is_not_cached_and_has_no_referrer(ctx: Ctx) -> None:
    _, challenge = _pkce()
    await ctx.client.post(
        f"{API}/auth/email/start", json={"email": EMAIL, "code_challenge": challenge}
    )
    link = ctx.mailer.sent[-1][1]
    page = await ctx.client.get(urlsplit(link).path + "?" + urlsplit(link).query)
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"


async def test_same_email_different_case_is_one_user(ctx: Ctx) -> None:
    first = await _sign_in(ctx, "Sam@Example.com")
    second = await _sign_in(ctx, "sam@example.com")
    assert first["user"]["id"] == second["user"]["id"]


async def test_login_is_audited_without_tokens(ctx: Ctx) -> None:
    tokens = await _sign_in(ctx)
    async with ctx.engine.connect() as conn:
        rows = (await conn.execute(text("SELECT action, detail::text FROM audit_log"))).all()
    assert [r[0] for r in rows] == ["login"]
    assert tokens["refresh_token"] not in rows[0][1]
    assert tokens["access_token"] not in rows[0][1]


# --- One-time code ----------------------------------------------------------------------


async def test_code_has_60_second_ttl_and_expired_code_is_rejected(ctx: Ctx) -> None:
    code, verifier = await _email_code(ctx)
    key = f"auth:code:{sha256_hex(code)}"
    ttl = await ctx.redis.ttl(key)
    assert 0 < ttl <= 60
    await ctx.redis.pexpire(key, 1)
    while await ctx.redis.exists(key):
        pass

    resp = await ctx.client.post(
        f"{API}/auth/exchange", json={"code": code, "code_verifier": verifier}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_code"


async def test_reused_code_is_rejected(ctx: Ctx) -> None:
    code, verifier = await _email_code(ctx)
    body = {"code": code, "code_verifier": verifier}
    assert (await ctx.client.post(f"{API}/auth/exchange", json=body)).status_code == 200
    again = await ctx.client.post(f"{API}/auth/exchange", json=body)
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "invalid_code"


async def test_wrong_pkce_verifier_is_rejected_and_burns_the_code(ctx: Ctx) -> None:
    code, verifier = await _email_code(ctx)
    wrong = await ctx.client.post(
        f"{API}/auth/exchange", json={"code": code, "code_verifier": new_token(48)}
    )
    assert wrong.status_code == 400
    right = await ctx.client.post(
        f"{API}/auth/exchange", json={"code": code, "code_verifier": verifier}
    )
    assert right.status_code == 400


async def test_magic_link_works_once(ctx: Ctx) -> None:
    await _email_code(ctx)
    link = ctx.mailer.sent[-1][1]
    again = await ctx.client.get(urlsplit(link).path + "?" + urlsplit(link).query)
    assert again.status_code == 400
    assert again.json()["error"]["code"] == "invalid_link"


async def test_callback_without_parameters_is_rejected(ctx: Ctx) -> None:
    resp = await ctx.client.get(f"{API}/auth/callback")
    assert resp.status_code == 400


async def test_email_start_is_rate_limited(ctx: Ctx) -> None:
    _, challenge = _pkce()
    body = {"email": EMAIL, "code_challenge": challenge}
    for _ in range(ctx.settings.email_login_max_per_window):
        assert (await ctx.client.post(f"{API}/auth/email/start", json=body)).status_code == 200
    blocked = await ctx.client.post(f"{API}/auth/email/start", json=body)
    assert blocked.status_code == 429


async def test_validation_errors_use_the_error_shape_and_hide_values(ctx: Ctx) -> None:
    resp = await ctx.client.post(
        f"{API}/auth/email/start", json={"email": "not-an-email", "code_challenge": "short"}
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation_error"
    assert "not-an-email" not in resp.text


# --- Refresh and logout -----------------------------------------------------------------


async def test_refresh_rotates_and_old_token_is_rejected(ctx: Ctx) -> None:
    tokens = await _sign_in(ctx, device_id=str(uuid.uuid4()))
    first = await ctx.client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert first.status_code == 200
    rotated = first.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    assert (
        await ctx.client.get(f"{API}/me", headers=_bearer(rotated["access_token"]))
    ).status_code == 200

    replay = await ctx.client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "invalid_refresh_token"


async def test_replaying_an_old_refresh_token_signs_the_device_out(ctx: Ctx) -> None:
    device = str(uuid.uuid4())
    tokens = await _sign_in(ctx, device_id=device)
    other_device = await _sign_in(ctx, device_id=str(uuid.uuid4()))
    rotated = (
        await ctx.client.post(
            f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    ).json()

    await ctx.client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})

    stolen_family = await ctx.client.post(
        f"{API}/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert stolen_family.status_code == 401
    untouched = await ctx.client.post(
        f"{API}/auth/refresh", json={"refresh_token": other_device["refresh_token"]}
    )
    assert untouched.status_code == 200


async def test_logout_revokes_the_refresh_token(ctx: Ctx) -> None:
    tokens = await _sign_in(ctx)
    out = await ctx.client.post(
        f"{API}/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert out.status_code == 204
    resp = await ctx.client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401


async def test_logout_with_unknown_token_still_succeeds(ctx: Ctx) -> None:
    out = await ctx.client.post(f"{API}/auth/logout", json={"refresh_token": new_token(48)})
    assert out.status_code == 204


async def test_expired_refresh_token_is_rejected(ctx: Ctx) -> None:
    tokens = await _sign_in(ctx)
    async with ctx.engine.begin() as conn:
        await conn.execute(text("UPDATE refresh_tokens SET expires_at = now() - interval '1 day'"))
    resp = await ctx.client.post(
        f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401


async def test_only_the_hash_of_the_refresh_token_is_stored(ctx: Ctx) -> None:
    tokens = await _sign_in(ctx)
    async with ctx.engine.connect() as conn:
        hashes = (await conn.execute(text("SELECT token_hash FROM refresh_tokens"))).scalars().all()
    assert hashes == [sha256_hex(tokens["refresh_token"])]


# --- Access tokens ----------------------------------------------------------------------


async def test_me_requires_a_valid_access_token(ctx: Ctx) -> None:
    assert (await ctx.client.get(f"{API}/me")).status_code == 401
    assert (await ctx.client.get(f"{API}/me", headers=_bearer("garbage"))).status_code == 401


async def test_expired_access_token_is_rejected(ctx: Ctx) -> None:
    tokens = await _sign_in(ctx)
    past = datetime.now(UTC) - timedelta(minutes=1)
    expired = jwt.encode(
        {"sub": tokens["user"]["id"], "exp": past, "typ": "access"},
        ctx.settings.jwt_secret,
        algorithm=JWT_ALGORITHM,
    )
    resp = await ctx.client.get(f"{API}/me", headers=_bearer(expired))
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "token_expired"


async def test_token_signed_with_another_secret_is_rejected(ctx: Ctx) -> None:
    tokens = await _sign_in(ctx)
    forged = jwt.encode(
        {
            "sub": tokens["user"]["id"],
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "typ": "access",
        },
        "another-secret-that-is-long-enough-0123456789",
        algorithm=JWT_ALGORITHM,
    )
    assert (await ctx.client.get(f"{API}/me", headers=_bearer(forged))).status_code == 401


# --- Google -----------------------------------------------------------------------------


async def _google_start(ctx: Ctx, challenge: str) -> str:
    resp = await ctx.client.get(
        f"{API}/auth/google/start",
        params={"redirect": "crew://auth", "code_challenge": challenge},
    )
    assert resp.status_code == 302, resp.text
    location = urlsplit(resp.headers["location"])
    assert location.netloc == "accounts.google.com"
    query = parse_qs(location.query)
    assert query["redirect_uri"] == ["http://localhost:8000/api/v1/auth/callback"]
    return query["state"][0]


async def test_google_sign_in_happy_path(ctx: Ctx) -> None:
    verifier, challenge = _pkce()
    state = await _google_start(ctx, challenge)
    page = await ctx.client.get(
        f"{API}/auth/callback", params={"code": "google-code", "state": state}
    )
    assert page.status_code == 200, page.text
    resp = await ctx.client.post(
        f"{API}/auth/exchange",
        json={"code": _code_from_page(page.text), "code_verifier": verifier},
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == "ada@example.com"
    assert resp.json()["user"]["name"] == "Ada Lovelace"


async def test_google_state_works_once_and_unknown_state_is_rejected(ctx: Ctx) -> None:
    _, challenge = _pkce()
    state = await _google_start(ctx, challenge)
    params = {"code": "google-code", "state": state}
    assert (await ctx.client.get(f"{API}/auth/callback", params=params)).status_code == 200
    assert (await ctx.client.get(f"{API}/auth/callback", params=params)).status_code == 400
    unknown = await ctx.client.get(
        f"{API}/auth/callback", params={"code": "google-code", "state": "made-up"}
    )
    assert unknown.status_code == 400
    assert len(ctx.google.requests) == 2  # only the first callback reached Google


async def test_google_unverified_email_is_rejected(ctx: Ctx) -> None:
    ctx.google.userinfo["email_verified"] = False
    _, challenge = _pkce()
    state = await _google_start(ctx, challenge)
    resp = await ctx.client.get(
        f"{API}/auth/callback", params={"code": "google-code", "state": state}
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "email_not_verified"


async def test_google_failure_is_a_clean_error(ctx: Ctx) -> None:
    ctx.google.token_status = 400
    _, challenge = _pkce()
    state = await _google_start(ctx, challenge)
    resp = await ctx.client.get(
        f"{API}/auth/callback", params={"code": "google-code", "state": state}
    )
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "google_failed"


async def test_google_start_rejects_other_redirects(ctx: Ctx) -> None:
    _, challenge = _pkce()
    resp = await ctx.client.get(
        f"{API}/auth/google/start",
        params={"redirect": "https://evil.example/steal", "code_challenge": challenge},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_redirect"


async def test_google_not_configured(ctx: Ctx) -> None:
    ctx.app.state.settings = ctx.settings.model_copy(update={"google_client_id": ""})
    _, challenge = _pkce()
    resp = await ctx.client.get(
        f"{API}/auth/google/start",
        params={"redirect": "crew://auth", "code_challenge": challenge},
    )
    assert resp.status_code == 503
    assert resp.json()["error"]["code"] == "google_not_configured"


# --- CORS -------------------------------------------------------------------------------


async def test_cors_allows_the_desktop_webview_only(ctx: Ctx) -> None:
    allowed = await ctx.client.get(f"{API}/me", headers={"Origin": "http://localhost:1420"})
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:1420"
    other = await ctx.client.get(f"{API}/me", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers
