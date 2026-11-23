"""Token helpers and ids: no services needed."""

import time
import uuid

import pytest

from crew.auth.mailer import DevLogMailer, SmtpMailer, create_mailer
from crew.auth.tokens import (
    create_access_token,
    decode_access_token,
    pkce_challenge,
    require_jwt_secret,
    verify_pkce,
)
from crew.config import Settings
from crew.errors import AppError
from crew.ids import uuid7

SECRET = "test-only-jwt-secret-not-used-anywhere-real-0123456789"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, jwt_secret=SECRET, **overrides)  # type: ignore[arg-type]


def test_pkce_matches_rfc_7636_example() -> None:
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
    assert verify_pkce(verifier, "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
    assert not verify_pkce(verifier + "x", "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")


def test_access_token_round_trip() -> None:
    user_id = uuid7()
    token, expires_in = create_access_token(user_id, _settings())
    assert expires_in == 900
    assert decode_access_token(token, _settings()) == user_id


def test_short_jwt_secret_is_refused() -> None:
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        require_jwt_secret(Settings(_env_file=None, jwt_secret="too-short"))


def test_garbage_token_raises_app_error() -> None:
    with pytest.raises(AppError) as err:
        decode_access_token("not.a.token", _settings())
    assert err.value.status_code == 401


def test_uuid7_is_version_7_and_time_ordered() -> None:
    first = uuid7()
    time.sleep(0.002)
    second = uuid7()
    assert first.version == 7
    assert first.variant == uuid.RFC_4122
    assert first < second


def test_mailer_choice() -> None:
    assert isinstance(create_mailer(_settings()), DevLogMailer)
    assert isinstance(create_mailer(_settings(smtp_url="smtp://u:p@localhost:2525")), SmtpMailer)
    with pytest.raises(RuntimeError, match="SMTP_URL"):
        create_mailer(_settings(crew_env="prod"))
