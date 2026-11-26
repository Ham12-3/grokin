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
    api_prefix: str = "/api/v1"
    desktop_deep_link: str = "crew://auth"
    jwt_secret: str = Field(default="", repr=False)
    access_token_minutes: int = 15
    refresh_token_days: int = 30
    magic_link_minutes: int = 15
    auth_code_seconds: int = 60
    oauth_state_minutes: int = 10
    email_login_max_per_window: int = 5
    http_timeout_seconds: float = 10.0
    # Origins of the desktop webview (Vite in dev, Tauri's own scheme in builds).
    cors_origins: list[str] = [
        "http://localhost:1420",
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
    ]

    # Database / Redis / storage
    database_url: str = "postgresql+asyncpg://crew:crew@localhost:5432/crew"
    redis_url: str = "redis://localhost:6379/0"
    # Where Library files are kept: "local" (a folder on this server) or "s3".
    library_storage: Literal["local", "s3"] = "local"
    library_dir: str = "data/library"
    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "crew-library"
    s3_access_key: str = Field(default="", repr=False)
    s3_secret_key: str = Field(default="", repr=False)

    # AI
    llm_provider: Literal["anthropic", "fake"] = "anthropic"
    fake_llm_delay_seconds: float = 0.03
    anthropic_api_key: str = Field(default="", repr=False)
    crew_model: str = ""
    crew_small_model: str = ""
    crew_max_output_tokens: int = 16_000
    crew_max_steps: int = 40
    crew_max_run_tokens: int = 400_000
    crew_daily_token_budget: int = 2_000_000

    # Limits
    max_bots_per_user: int = 50
    chat_history_messages: int = 40
    run_timeout_seconds: int = 600
    partial_save_seconds: float = 1.0
    ws_max_subscriptions: int = 50
    cancel_poll_seconds: float = 0.3

    # Web search and fetch
    search_provider: str = "brave"
    search_api_key: str = Field(default="", repr=False)
    search_api_url: str = "https://api.search.brave.com/res/v1/web/search"
    search_result_count: int = 8
    web_fetch_max_bytes: int = 2_000_000
    web_fetch_timeout_seconds: float = 15.0

    # Files (local workspaces until the cloud computer arrives in phase 4)
    workspaces_dir: str = str(REPO_ROOT / "data" / "workspaces")
    file_max_bytes: int = 1_000_000

    # Auth providers
    google_client_id: str = ""
    google_client_secret: str = Field(default="", repr=False)
    google_auth_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_token_url: str = "https://oauth2.googleapis.com/token"  # noqa: S105
    google_userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    email_from: str = "Crew <no-reply@example.com>"
    smtp_url: str = Field(default="", repr=False)

    # Cloud computer
    computer_provider: Literal["docker", "e2b", "local"] = "docker"
    computer_image: str = "crew-computer:dev"
    computer_idle_minutes: int = 10
    computer_memory: str = "3g"
    computer_cpus: float = 2.0
    computer_pids_limit: int = 1024
    # Signs each computer's control token. Falls back to JWT_SECRET when empty.
    computer_token_secret: str = Field(default="", repr=False)
    display_claim_seconds: int = 3600
    takeover_timeout_seconds: int = 1800
    terminal_max_seconds: int = 300
    e2b_api_key: str = Field(default="", repr=False)

    # Connectors
    composio_api_key: str = Field(default="", repr=False)
    # Development only: lets a custom MCP server be on this machine or a private network.
    mcp_allow_private: bool = False

    # Vault
    vault_master_key: str = Field(default="", repr=False)
    vault_kms_key_id: str = ""

    # The oldest desktop app this API still works with. Older apps show "Please update".
    min_desktop_version: str = "0.1.0"

    # Observability
    sentry_dsn: str = Field(default="", repr=False)
    log_level: str = "INFO"

    # Health checks
    health_check_timeout_seconds: float = 2.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
