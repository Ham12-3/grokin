"""Token helpers: random tokens, hashing, PKCE and JWT access tokens."""

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt

from crew.config import Settings
from crew.errors import AppError, unauthorized

JWT_ALGORITHM = "HS256"
MIN_JWT_SECRET_LENGTH = 32
REFRESH_TOKEN_BYTES = 48


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def pkce_challenge(verifier: str) -> str:
    """S256 challenge: base64url(sha256(verifier)) without padding."""
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode()


def verify_pkce(verifier: str, challenge: str) -> bool:
    return hmac.compare_digest(pkce_challenge(verifier), challenge)


def require_jwt_secret(settings: Settings) -> str:
    if len(settings.jwt_secret) < MIN_JWT_SECRET_LENGTH:
        raise RuntimeError(
            f"JWT_SECRET must be at least {MIN_JWT_SECRET_LENGTH} characters. Generate one with: "
            'python -c "import secrets; print(secrets.token_urlsafe(48))"'
        )
    return settings.jwt_secret


def create_access_token(user_id: uuid.UUID, settings: Settings) -> tuple[str, int]:
    """Returns the signed token and its lifetime in seconds."""
    lifetime = timedelta(minutes=settings.access_token_minutes)
    now = datetime.now(UTC)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": now + lifetime, "typ": "access"},
        require_jwt_secret(settings),
        algorithm=JWT_ALGORITHM,
    )
    return token, int(lifetime.total_seconds())


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    try:
        claims = jwt.decode(
            token,
            require_jwt_secret(settings),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "typ"]},
        )
        if claims["typ"] != "access":
            raise unauthorized("invalid_token", "Invalid access token.")
        return uuid.UUID(claims["sub"])
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized("token_expired", "Access token expired.") from exc
    except (jwt.InvalidTokenError, ValueError) as exc:
        raise unauthorized("invalid_token", "Invalid access token.") from exc


__all__ = [
    "REFRESH_TOKEN_BYTES",
    "AppError",
    "create_access_token",
    "decode_access_token",
    "new_token",
    "pkce_challenge",
    "require_jwt_secret",
    "sha256_hex",
    "verify_pkce",
]
