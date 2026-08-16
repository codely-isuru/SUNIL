"""Application settings — the single seam that reads process environment.

Every field here corresponds to a row in `docs/ARCHITECTURE_V1.md` §14.4,
including the three variables added by the owner's review:
`SUNIL_CONFIG_DIR`, `SUNIL_TURN_DEADLINE_S` (default 40) and
`SUNIL_PROGRESS_EVENTS` (default `false`); and `anthropic_base_url` /
`github_api_base_url`, added by the Architect's ADR-017 ruling (A-11) —
see that field's own comment for why passing them explicitly is a ruling,
not a style preference.

**Cross-lane note (BE-2, 2026-08-14):** this file is owned by T1/T5. The
two `*_base_url` fields and their shared loopback validator below were
added here — ahead of T1/T5 picking up the ADR-017 delta — because T6's
own fix (`providers/anthropic.py` passing `base_url=` explicitly) cannot
exist without the setting to pass, and the Delivery Manager asked for the
base-URL fix specifically not to wait behind other work. This is a small,
fully-specified, additive change (two fields + one validator, nothing
existing touched) so it should rebase cleanly whichever lane finishes
next; flagged in the T6 report rather than merged from the shadows.

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
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/sunil/settings.py -> sunil -> api -> apps -> repo root.
# `.env` lives at the repo root (docs/ARCHITECTURE_V1.md §2.2, §14.1), not
# under apps/api, so this is resolved relative to this file rather than to
# the process's current working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"

_REDACTED_INPUT_PLACEHOLDER = "<redacted — a failed Settings() load never exposes loaded values>"


def _redact_validation_error(exc: ValidationError) -> ValidationError:
    """Re-raise a `Settings` construction failure with every `input` value
    stripped (ET-10, security review blocker 3).

    On a *missing*-field error, pydantic reports `input` as the **entire
    collected values dict so far** — and `SecretStr` coercion happens only
    after validation succeeds, so at that moment every other secret that
    *did* load is still a raw `str` inside that dict. It then rides inside
    `.errors()`, `.json()`, `str(exc)`/`repr(exc)`, and a traceback. This is
    the one path T4's redaction registry cannot rescue: on this path no
    secret loaded successfully, so nothing was ever registered there
    either.

    `type` / `loc` / `ctx` are preserved so the human-readable message is
    unchanged (`ctx` carries only constraint parameters — an `enum` list,
    a `ge` bound — never a copy of the offending input); only `input` is
    replaced. The result is still a real `pydantic.ValidationError`, so
    `except ValidationError` at every existing call site keeps working
    unchanged.
    """
    line_errors = []
    for error in exc.errors():
        line_error: dict[str, Any] = {
            "type": error["type"],
            "loc": error["loc"],
            "input": _REDACTED_INPUT_PLACEHOLDER,
        }
        if "ctx" in error:
            line_error["ctx"] = error["ctx"]
        line_errors.append(line_error)
    return ValidationError.from_exception_data(exc.title, line_errors, hide_input=True)


# ADR-017 §9.7 / A-11: the one canonical value per upstream base URL.
# A non-canonical value must be loopback, checked by `_validate_base_url`
# below, or `Settings` refuses to construct and the app does not boot —
# "enforced by construction rather than by an environment flag" (ADR-017).
_CANONICAL_BASE_URLS: dict[str, str] = {
    "anthropic_base_url": "https://api.anthropic.com",
    "github_api_base_url": "https://api.github.com",
}


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False  # not an IP literal and not "localhost" — not loopback


def _validate_base_url(field_name: str, value: str) -> str:
    """Shared by both `*_base_url` fields (ADR-017 §9.7): the value equals
    the canonical host, or its host is loopback (`localhost`,
    `127.0.0.0/8`, `::1` — a local test double), or `Settings` construction
    fails. There is no third case: an env-settable, unguarded API base is
    an exfiltration channel (a redirected GitHub URL carries
    `Authorization: Bearer <PAT>` to whatever host is named)."""
    canonical = _CANONICAL_BASE_URLS[field_name]
    if value == canonical:
        return value
    host = urlparse(value).hostname
    if host and _is_loopback_host(host):
        return value
    raise ValueError(
        f"{field_name} must be the canonical host ({canonical!r}) or a loopback "
        f"address (localhost / 127.0.0.0/8 / ::1) for local testing — got {value!r} "
        "(ADR-017 §9.7)"
    )


class Settings(BaseSettings):
    """Typed, validated process configuration for the SUNIL API."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **values: Any) -> None:
        """Sanitise a validation failure before it ever leaves this class.

        The `raise` deliberately happens *outside* the `except` block: a
        `raise` written inside an `except ValidationError as exc:` clause
        implicitly chains the new exception's `__context__` to `exc`,
        regardless of `from None` (which only suppresses *display* of the
        chain — the original, secret-carrying exception object stays
        reachable via `__context__` otherwise). Falling through the
        `except` before raising means there is no exception being handled
        at that point, so `__context__` is never set at all — not merely
        hidden from a traceback.
        """
        sanitized: ValidationError | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            sanitized = _redact_validation_error(exc)
        if sanitized is not None:
            raise sanitized

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

    # -- Upstream base URLs (A-11, ADR-017) ---------------------------------
    # `github_api_base_url` started life as a T8 ad hoc, unvalidated addition
    # (QA's fixture tests were hitting the real GitHub API with a placeholder
    # token and getting a real 401 — the host was hard-coded with no
    # override), and was independently formalised here under ADR-017 with
    # `anthropic_base_url`'s same loopback-or-canonical validator. More than
    # one branch carried a T8-era copy of the field; every merge keeps the
    # single ADR-017-validated definition below (with
    # `_check_github_api_base_url` coverage) and drops the earlier
    # unvalidated duplicate — a class body redefining the same field name
    # twice is exactly the kind of drift a single canonical definition
    # exists to prevent.
    # Passed **explicitly** to each client/adapter — never left to the SDK's
    # own environment reading. Read from the installed anthropic SDK's
    # `_client.py`, precedence is kwarg -> ANTHROPIC_BASE_URL -> profile ->
    # default; a hard-coded canonical kwarg would outrank the env var and
    # silently point the whole exit suite at the real API with a real key.
    anthropic_base_url: str = Field(
        default="https://api.anthropic.com",
        description="providers/anthropic — passed as base_url= explicitly. Non-canonical "
        "values must be loopback (§9.7).",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        description="tools/github — prefixed onto every request path. Non-canonical values "
        "must be loopback (§9.7).",
    )

    @field_validator("anthropic_base_url")
    @classmethod
    def _check_anthropic_base_url(cls, value: str) -> str:
        return _validate_base_url("anthropic_base_url", value)

    @field_validator("github_api_base_url")
    @classmethod
    def _check_github_api_base_url(cls, value: str) -> str:
        return _validate_base_url("github_api_base_url", value)

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
