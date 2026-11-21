"""Settings for the API and the worker, read from the environment and `.env`."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# services/shared/crew/config.py -> the repo root is three levels above `crew/`.
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Every limit, URL and model name comes from here, never from a literal in the code."""

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # App
    crew_env: Literal["dev", "test", "prod"] = "dev"
    api_base_url: str = "http://localhost:8000"
    desktop_deep_link: str = "crew://auth"
    jwt_secret: str = Field(default="", repr=False)
    access_token_minutes: int = 15
    refresh_token_days: int = 30

    # Database / Redis / storage
    database_url: str = "postgresql+asyncpg://crew:crew@localhost:5432/crew"
    redis_url: str = "redis://localhost:6379/0"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "crew-library"
    s3_access_key: str = Field(default="", repr=False)
    s3_secret_key: str = Field(default="", repr=False)

    # AI
    anthropic_api_key: str = Field(default="", repr=False)
    crew_model: str = ""
    crew_small_model: str = ""
    crew_max_steps: int = 40
    crew_daily_token_budget: int = 2_000_000

    # Web search
    search_provider: str = "brave"
    search_api_key: str = Field(default="", repr=False)

    # Auth providers
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    email_from: str = "Crew <no-reply@example.com>"
    smtp_url: str = Field(default="", repr=False)

    # Cloud computer
    computer_provider: Literal["docker", "e2b"] = "docker"
    computer_image: str = "crew-computer:dev"
    computer_idle_minutes: int = 10
    e2b_api_key: str = Field(default="", repr=False)

    # Connectors
    composio_api_key: str = Field(default="", repr=False)

    # Vault
    vault_master_key: str = Field(default="", repr=False)
    vault_kms_key_id: str = ""

    # Observability
    sentry_dsn: str = Field(default="", repr=False)
    log_level: str = "INFO"

    # Health checks
    health_check_timeout_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
