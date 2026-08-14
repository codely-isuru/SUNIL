"""Application settings — the single seam that reads process environment.

Every field here corresponds to a row in `docs/ARCHITECTURE_V1.md` §14.4,
including the three variables added by the owner's review:
`SUNIL_CONFIG_DIR`, `SUNIL_TURN_DEADLINE_S` (default 40) and
`SUNIL_PROGRESS_EVENTS` (default `false`).

No other module should call `os.environ` / `os.getenv` directly — go
through `get_settings()` so there is exactly one place configuration is
read, validated and typed.

Secrets are `SecretStr`, never `str`: their raw value cannot leak through a
`repr()`, a `str()`, an accidental `print()`, or a structlog field — callers
must call `.get_secret_value()` explicitly, at the point of use, which
keeps a secret leak a deliberate act rather than an accident.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/sunil/settings.py -> sunil -> api -> apps -> repo root.
# `.env` lives at the repo root (docs/ARCHITECTURE_V1.md §2.2, §14.1), not
# under apps/api, so this is resolved relative to this file rather than to
# the process's current working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Typed, validated process configuration for the SUNIL API."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Database ---------------------------------------------------------
    # `SecretStr` because a Postgres URL commonly carries embedded
    # credentials (docs/ARCHITECTURE_V1.md §14.4: "contains one when
    # Postgres"); the SQLite default carries none but the type stays
    # uniform so no call site has to know which backend is configured.
    database_url: SecretStr = Field(
        default=SecretStr("sqlite+aiosqlite:///./var/sunil.db"),
        description="SQLAlchemy async URL (db/session). May embed credentials on Postgres.",
    )

    # -- Provider / integration secrets ------------------------------------
    anthropic_api_key: SecretStr = Field(
        description="Anthropic API key, used only by sunil/providers/anthropic.py."
    )
    github_token: SecretStr = Field(
        description="Read-only GitHub PAT, used only by sunil/tools/github."
    )

    # -- Session ------------------------------------------------------------
    session_secret: SecretStr = Field(description="Signing key for SessionMiddleware's cookie.")
    session_cookie_name: str = Field(default="sunil_session")

    # -- CORS / origin -------------------------------------------------------
    web_origin: str = Field(
        default="http://localhost:3000",
        description="The single allowed CORS origin. Never '*' with allow_credentials=True.",
    )

    # -- uvicorn --------------------------------------------------------------
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)

    # -- logging ----------------------------------------------------------------
    log_level: str = Field(default="INFO")

    # -- Feature flags / turn control (owner's review additions) -----------------
    sunil_progress_events: bool = Field(
        default=False,
        description="SSE progress channel feature flag (T12, optional/post-M1). Ships false.",
    )
    sunil_config_dir: str = Field(
        default="./config",
        description="Directory the registry loaders (config/*.yaml) read from (ADR-016).",
    )
    sunil_turn_deadline_s: int = Field(
        default=40,
        description="Server-side per-turn deadline, seconds (§5.3), below the 45s client timeout.",
    )

    # -- Owner account (seed script only) ------------------------------------------
    owner_username: str = Field(description="Login username, used only by scripts/seed-owner.py.")
    owner_password: SecretStr = Field(
        description="Login password, used only by scripts/seed-owner.py."
    )

    # -- Frontend --------------------------------------------------------------------
    # Not consumed by the backend; recorded here only so the §14.4 inventory
    # has exactly one home and CI can validate `.env.example` against it.
    next_public_api_base_url: str = Field(default="http://localhost:8000")


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings instance.

    `lru_cache` gives one instance per process, which is what lets settings
    be read cheaply from any module without re-parsing the environment or
    re-reading `.env` on every call.
    """
    return Settings()
