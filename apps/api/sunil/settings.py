"""Application settings — the single seam that reads process environment.

Every field is a row of `docs/ARCHITECTURE_V2.md` §5's config inventory, in the
inventory's own order. **Nothing else in the codebase reads the environment**
(the M1 law, kept): no `os.environ`, no `os.getenv`, no SDK reading its own
`*_API_KEY` — go through `Settings`, so configuration is read, validated and
typed in exactly one place.

Two validator families, both fail-closed at construction time — the app does not
boot on a bad value rather than discovering it on the first request:

* **ADR-033's named-host rule** (`sunil_llm_gateway_base_url`,
  `sunil_n8n_mcp_base_url`, `sunil_approval_notify_webhook_url`): loopback, or
  the literal Compose service host, or nothing. An env-settable, unguarded
  outbound base is an exfiltration channel — a redirected gateway URL carries
  `Authorization: Bearer <virtual key>` and the whole prompt to whatever host is
  named (TB2/TB5/TB8 in §4).
* **ADR-017's canonical hosts** for the direct provider lane
  (`anthropic_base_url`, `openai_base_url`): the canonical value or loopback.

Secrets are `SecretStr`, never `str`: the raw value cannot leak through a
`repr()`, a `str()`, a stray `print()` or a structlog field — a caller must ask
for it by name at the point of use, which keeps a leak a deliberate act.
`register_secrets_from_settings()` (`sunil.redaction`) then registers those
values so anything that *does* reach a log line is replaced.
"""

from __future__ import annotations

from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/api/sunil/settings.py -> sunil -> api -> apps -> repo root. `.env` lives
# at the repo root (§5), not under apps/api, so it is resolved relative to this
# file and never to the process's working directory.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_FILE = _REPO_ROOT / ".env"

_REDACTED_INPUT = "<redacted — a failed Settings() load never exposes loaded values>"


def _redact_validation_error(exc: ValidationError) -> ValidationError:
    """Re-raise a construction failure with every `input` value stripped.

    On a *missing*-field error pydantic reports `input` as the entire collected
    values dict — and `SecretStr` coercion happens only after validation
    succeeds, so at that moment every secret that DID load is still a raw `str`
    inside that payload, riding inside `.errors()`, `str(exc)` and any traceback.
    This is the one path the redaction registry cannot rescue: on this path
    nothing was ever registered there either. `type`/`loc`/`ctx` are preserved
    (ctx carries constraint parameters, never the offending input), so the
    human-readable message is unchanged and `except ValidationError` call sites
    keep working.
    """
    line_errors = []
    for error in exc.errors():
        line_error: dict[str, Any] = {
            "type": error["type"],
            "loc": error["loc"],
            "input": _REDACTED_INPUT,
        }
        if "ctx" in error:
            line_error["ctx"] = error["ctx"]
        line_errors.append(line_error)
    return ValidationError.from_exception_data(exc.title, line_errors, hide_input=True)


#: ADR-033 — the named in-network hosts each outbound base URL may legally use
#: (§5's "legal under ADR-033's named-host rule" for the container lane). Exact
#: host equality, never a substring: `litellm.evil.example` is not `litellm`.
_NAMED_HOSTS: dict[str, tuple[str, ...]] = {
    "sunil_llm_gateway_base_url": ("litellm",),
    "sunil_n8n_mcp_base_url": ("n8n",),
    "sunil_approval_notify_webhook_url": ("n8n",),
}

#: ADR-017 — the one canonical value per direct-lane provider base URL.
_CANONICAL_BASE_URLS: dict[str, str] = {
    "anthropic_base_url": "https://api.anthropic.com",
    "openai_base_url": "https://api.openai.com/v1",
}


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False  # neither an IP literal nor "localhost" — not loopback


def _validate_named_host_url(field_name: str, value: str) -> str:
    """ADR-033: loopback, or one of the field's named Compose hosts, or refuse."""
    host = urlparse(value).hostname
    allowed = _NAMED_HOSTS[field_name]
    if host and (_is_loopback_host(host) or host in allowed):
        return value
    raise ValueError(
        f"{field_name} must be a loopback address (localhost / 127.0.0.0/8 / ::1) "
        f"or one of the named Compose hosts {allowed} — got {value!r} (ADR-033)"
    )


def _validate_canonical_base_url(field_name: str, value: str) -> str:
    canonical = _CANONICAL_BASE_URLS[field_name]
    if value == canonical:
        return value
    host = urlparse(value).hostname
    if host and _is_loopback_host(host):
        return value
    raise ValueError(
        f"{field_name} must be the canonical host ({canonical!r}) or a loopback "
        f"address for a local test double — got {value!r} (ADR-017)"
    )


class Settings(BaseSettings):
    """Typed, validated process configuration for the SUNIL V2 API."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **values: Any) -> None:
        """Sanitise a validation failure before it can leave this class.

        The `raise` deliberately happens *outside* the `except` block: raising
        inside `except ValidationError as exc` chains the new exception's
        `__context__` to `exc` regardless of `from None` (which suppresses only
        the *display*), leaving the secret-carrying original reachable. Falling
        through the `except` first means no exception is being handled at the
        point of the raise, so `__context__` is never set at all.
        """
        sanitised: ValidationError | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            sanitised = _redact_validation_error(exc)
        if sanitised is not None:
            raise sanitised

    # -- Database (§5) ------------------------------------------------------ #
    # `+psycopg` (psycopg v3) is normative: ADR-002's recorded driver, and one
    # dependency serves both SQLAlchemy 2's async engine and Alembic's sync
    # migration path. Host port 5433 — ADR-032 Amendment 1.
    database_url: SecretStr = Field(
        default=SecretStr("postgresql+psycopg://sunil:CHANGE_ME@localhost:5433/sunil"),
        description="SQLAlchemy async URL (db/session). Embeds the Postgres password.",
    )

    # -- Session / auth (§5, ADR-007) --------------------------------------- #
    # Deliberately no default: a defaulted signing key means every deployment
    # that forgot to set one shares a forgeable cookie, silently.
    session_secret: SecretStr = Field(description="Signing key for SessionMiddleware's cookie.")
    session_cookie_name: str = Field(default="sunil_session")

    # -- CORS / origin (§5, ADR-008 + ADR-032 Amendment 1) ------------------ #
    web_origin: str = Field(
        default="http://localhost:3001",
        description="The single allowed CORS origin. Never '*' with allow_credentials=True.",
    )

    # -- uvicorn bind (§5) --------------------------------------------------- #
    api_host: str = Field(default="127.0.0.1")
    api_port: int = Field(default=8000)

    # -- logging (§5) -------------------------------------------------------- #
    log_level: str = Field(default="INFO")

    # -- registry + turn control (§5) ---------------------------------------- #
    sunil_config_dir: str = Field(
        default="./config",
        description="Directory the registry loaders (config/*.yaml) read from (ADR-016).",
    )
    sunil_turn_deadline_s: int = Field(
        default=40,
        gt=0,
        description="Server-side per-turn deadline, seconds. Normative at 40 (§5's ruling): "
        "tight enough that a hang surfaces in dev. A parked turn's human wait is "
        "OUTSIDE this deadline (§6) — that is why ADR-031 parks.",
    )

    # -- provider lane (§5, ADR-033) ----------------------------------------- #
    # Transport wiring ONLY, invisible to router policy: the router resolves
    # (capability × privacy) and the lane decides how the bytes travel.
    sunil_llm_provider_lane: Literal["gateway", "direct", "fake"] = Field(default="gateway")
    sunil_llm_gateway_base_url: str = Field(default="http://localhost:4000")
    anthropic_base_url: str = Field(default="https://api.anthropic.com")
    openai_base_url: str = Field(default="https://api.openai.com/v1")
    # Provider keys: unset in the gateway lane, where they live ONLY in the
    # litellm container's env (TB3). Present here for the direct kill-switch
    # lane and for Stream B to read.
    litellm_virtual_key_default: SecretStr | None = Field(default=None)
    anthropic_api_key: SecretStr | None = Field(default=None)
    openai_api_key: SecretStr | None = Field(default=None)

    # -- tools / MCP (§5) ---------------------------------------------------- #
    github_token: SecretStr | None = Field(
        default=None,
        description="Injected into the github_mcp child env at spawn (C1 §5). Required only "
        "when a github server is configured — absence must not stop the app booting.",
    )
    sunil_n8n_mcp_base_url: str = Field(default="http://localhost:5680/mcp")
    sunil_n8n_mcp_auth_token: SecretStr | None = Field(default=None)

    # -- approvals (§5, C4) --------------------------------------------------- #
    sunil_approval_ttl_hours: int = Field(default=72, gt=0)
    sunil_approval_consume_grace_hours: int = Field(default=1, gt=0)
    sunil_approval_notify_webhook_url: str | None = Field(
        default=None, description="Unset = webhook off; dashboard polling is the notify path."
    )

    # -- machine lane (§5, ADR-035) ------------------------------------------- #
    # Unset = the machine lane is OFF. That is the fail-closed application
    # default even though scripts/dev-up generates one into a fresh `.env`.
    sunil_service_token: SecretStr | None = Field(default=None)

    # -- seam selection (§3's plug order) ------------------------------------- #
    # Each names WHICH implementation of a frozen contract is wired. `fake`
    # requires an injected seam (sunil.api.wiring.Seams) — production code never
    # imports test doubles; see that module.
    sunil_memory_provider: Literal["fake", "mem0"] = Field(default="fake")
    sunil_tool_manager: Literal["fake", "real"] = Field(default="real")
    sunil_approvals_service: Literal["fake", "real"] = Field(default="real")

    # -- Frontend (recorded so §5 has exactly one home; not read by the API) -- #
    next_public_api_base_url: str = Field(default="http://localhost:8000")

    # -- validators ----------------------------------------------------------- #
    @field_validator("sunil_llm_gateway_base_url")
    @classmethod
    def _check_gateway_base_url(cls, value: str) -> str:
        return _validate_named_host_url("sunil_llm_gateway_base_url", value)

    @field_validator("sunil_n8n_mcp_base_url")
    @classmethod
    def _check_n8n_mcp_base_url(cls, value: str) -> str:
        return _validate_named_host_url("sunil_n8n_mcp_base_url", value)

    @field_validator("sunil_approval_notify_webhook_url")
    @classmethod
    def _check_notify_webhook_url(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        return _validate_named_host_url("sunil_approval_notify_webhook_url", value)

    @field_validator("anthropic_base_url")
    @classmethod
    def _check_anthropic_base_url(cls, value: str) -> str:
        return _validate_canonical_base_url("anthropic_base_url", value)

    @field_validator("openai_base_url")
    @classmethod
    def _check_openai_base_url(cls, value: str) -> str:
        return _validate_canonical_base_url("openai_base_url", value)

    @field_validator("web_origin")
    @classmethod
    def _check_web_origin(cls, value: str) -> str:
        """§5: `localhost`, never `127.0.0.1`. The API may BIND 127.0.0.1, but
        the browser-facing name must be `localhost` or the session cookie is not
        same-site with the page (ADR-008)."""
        host = urlparse(value).hostname
        if host == "localhost":
            return value
        raise ValueError(
            f"web_origin must be a http(s)://localhost[:port] origin — got {value!r}. "
            "The cookie is same-site with the page only if both are 'localhost' (ADR-008)."
        )


@lru_cache
def get_settings() -> Settings:
    """Process-wide cached settings, for contexts that have **no `app`** —
    Alembic, `scripts/*`, one-shot CLI work.

    Request-path code must never call this: `create_app()` builds one `Settings`
    per application and stores it on `app.state` (ADR-018), which is what lets
    two apps with two `DATABASE_URL`s coexist in one test process.
    """
    return Settings()
