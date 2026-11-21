"""Settings load from the environment and never show secrets in repr."""

import pytest

from crew.config import REPO_ROOT, Settings


def test_defaults_without_env_file() -> None:
    s = Settings(_env_file=None)
    assert s.crew_max_steps == 40
    assert s.computer_provider == "docker"


def test_env_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREW_MODEL", "some-model")
    monkeypatch.setenv("CREW_MAX_STEPS", "7")
    s = Settings(_env_file=None)
    assert s.crew_model == "some-model"
    assert s.crew_max_steps == 7


def test_secrets_hidden_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JWT_SECRET", "test-only-not-a-real-secret")
    assert "test-only-not-a-real-secret" not in repr(Settings(_env_file=None))


def test_env_example_parses() -> None:
    s = Settings(_env_file=REPO_ROOT / ".env.example")
    assert s.smtp_url == ""
    assert s.computer_provider == "docker"
