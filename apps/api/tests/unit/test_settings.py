"""Unit tests for `sunil.settings.Settings` (T1 — FR-005, FR-008).

These exist so T21's `pytest` job never collects zero tests (pytest exits
5 on an empty suite, which a naive CI check would treat as a pass —
`docs/M1_BUILD_PLAN.md` §2 T1 "Watch").

Every test disables `.env` file loading (`Settings(_env_file=None)`) and
sets only fake, obviously-non-real values via `monkeypatch`, so this suite
never depends on — and never risks leaking — a real credential (ET-10).
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError
from sunil.settings import Settings

# Fake values only. None of these are, or resemble, a real credential.
REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-fake-test-value",
    "GITHUB_TOKEN": "github_pat_fake-test-value",
    "SESSION_SECRET": "fake-test-session-secret-value",
    "OWNER_USERNAME": "test-owner",
    "OWNER_PASSWORD": "fake-test-owner-password",
}


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)


def test_settings_loads_every_required_variable_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)

    settings = Settings(_env_file=None)

    assert settings.anthropic_api_key.get_secret_value() == REQUIRED_ENV["ANTHROPIC_API_KEY"]
    assert settings.github_token.get_secret_value() == REQUIRED_ENV["GITHUB_TOKEN"]
    assert settings.session_secret.get_secret_value() == REQUIRED_ENV["SESSION_SECRET"]
    assert settings.owner_username == REQUIRED_ENV["OWNER_USERNAME"]
    assert settings.owner_password.get_secret_value() == REQUIRED_ENV["OWNER_PASSWORD"]


def test_missing_required_secret_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env configured at all: Settings must refuse to construct, not fall
    back to an empty or guessed secret."""
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_a_failed_settings_load_never_exposes_an_already_loaded_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Security review blocker 3: pydantic reports a *missing* field with
    `input` set to the whole collected-so-far values dict, and `SecretStr`
    coercion happens only after validation succeeds — so at the moment of
    failure every *other* secret that did load is still a raw `str` and
    would otherwise ride along inside the exception verbatim. Delete only
    one required variable so the other secrets are the ones still "loaded"
    at the moment of failure, matching the real failure shape exactly.
    """
    _set_required_env(monkeypatch)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://sunil:FakeDbPassLeak@db:5432/sunil")
    monkeypatch.delenv("OWNER_PASSWORD", raising=False)  # the one field that is actually missing

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    exc = excinfo.value
    renderings = {
        "str(exc)": str(exc),
        "repr(exc)": repr(exc),
        "exc.json()": exc.json(),
        "exc.errors() as text": str(exc.errors()),
    }
    needles = {
        "ANTHROPIC_API_KEY": REQUIRED_ENV["ANTHROPIC_API_KEY"],
        "GITHUB_TOKEN": REQUIRED_ENV["GITHUB_TOKEN"],
        "SESSION_SECRET": REQUIRED_ENV["SESSION_SECRET"],
        "DATABASE_URL password": "FakeDbPassLeak",
    }
    leaks = [
        f"{rendering} leaks {name}"
        for rendering, text in renderings.items()
        for name, needle in needles.items()
        if needle in text
    ]
    assert not leaks, "a failed Settings() construction exposed already-loaded secrets:\n  " + (
        "\n  ".join(leaks)
    )
    # The exception is still a real, catchable ValidationError — the fix
    # must not change what every existing `except ValidationError` call
    # site can rely on.
    assert isinstance(exc, ValidationError)
    # Nor does the original, secret-carrying exception stay reachable via
    # exception chaining — `except ValidationError as exc: raise
    # new_exc from exc` would still leave it on `__context__`/`__cause__`.
    assert exc.__context__ is None
    assert exc.__cause__ is None


def test_owner_review_additions_have_the_agreed_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The three variables the owner's review added, with their agreed
    defaults (docs/M1_BUILD_PLAN.md §2 T1)."""
    _set_required_env(monkeypatch)
    for key in ("SUNIL_CONFIG_DIR", "SUNIL_TURN_DEADLINE_S", "SUNIL_PROGRESS_EVENTS"):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.sunil_config_dir == "./config"
    assert settings.sunil_turn_deadline_s == 40
    assert settings.sunil_progress_events is False


def test_secrets_are_secretstr_and_never_appear_in_repr_or_str(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_required_env(monkeypatch)
    fake_db_url = "postgresql+psycopg://sunil:FakeDbPassNeverLeaks@db:5432/sunil"
    monkeypatch.setenv("DATABASE_URL", fake_db_url)

    settings = Settings(_env_file=None)

    # Includes `database_url` — the one secret that carries an embedded
    # credential (a prior revision of this test omitted it).
    secret_field_values = {
        "anthropic_api_key": REQUIRED_ENV["ANTHROPIC_API_KEY"],
        "github_token": REQUIRED_ENV["GITHUB_TOKEN"],
        "session_secret": REQUIRED_ENV["SESSION_SECRET"],
        "owner_password": REQUIRED_ENV["OWNER_PASSWORD"],
        "database_url": fake_db_url,
    }
    for field_name, raw in secret_field_values.items():
        value = getattr(settings, field_name)

        assert isinstance(value, SecretStr)
        assert raw not in repr(value)
        assert raw not in str(value)
        assert raw not in repr(settings)


def test_database_url_defaults_to_sqlite_and_is_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = Settings(_env_file=None)

    assert isinstance(settings.database_url, SecretStr)
    assert settings.database_url.get_secret_value() == "sqlite+aiosqlite:///./var/sunil.db"


def test_non_secret_defaults_match_the_architecture_inventory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """docs/ARCHITECTURE_V1.md §14.4 — the non-secret defaults, byte for
    byte, so a future edit to this table is caught here."""
    _set_required_env(monkeypatch)
    for key in (
        "SESSION_COOKIE_NAME",
        "WEB_ORIGIN",
        "API_HOST",
        "API_PORT",
        "LOG_LEVEL",
        "NEXT_PUBLIC_API_BASE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings(_env_file=None)

    assert settings.session_cookie_name == "sunil_session"
    assert settings.web_origin == "http://localhost:3000"
    assert settings.api_host == "127.0.0.1"
    assert settings.api_port == 8000
    assert settings.log_level == "INFO"
    assert settings.next_public_api_base_url == "http://localhost:8000"


def test_settings_is_cached_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """`get_settings()` returns the same instance on repeat calls within a
    process (so it is cheap to call from any module), without ever reading
    a real `.env` in this test process."""
    _set_required_env(monkeypatch)

    from sunil.settings import get_settings

    get_settings.cache_clear()
    try:
        first = get_settings()
        second = get_settings()
        assert first is second
    finally:
        get_settings.cache_clear()
