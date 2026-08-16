"""Builds a real, running SUNIL app for exit tests, plus the thin HTTP helpers every
exit test shares — written against the frozen docs/M1_BUILD_PLAN.md §6/§6.1 contract.

Every function here is a PLAIN function (never a `@pytest.fixture`); call these from
inside a test's own body so a missing module surfaces as a FAILED test, not a
collection/fixture-setup ERROR — see tests/_helpers.py's docstring for why that
distinction is the whole point of this harness being "red for the right reason".

RULED, not assumed (see docs/decisions/ADR-017-test-seams-and-base-url-overrides.md and
ADR-018-application-and-settings-lifecycle.md — both accepted 2026-08-14, in response to
exactly the questions this file's previous revision flagged):

  1. **The application is the unit of configuration isolation (ADR-018).** There is no
     supported `cache_clear()`-based test seam for the app: `create_app(settings=...)`
     accepts a `Settings` instance directly, and a test builds a fresh one per app it
     needs. `get_settings()`/`get_app_engine()` stay `lru_cache`d, but that scope now
     narrows to contexts with no `app` — scripts, Alembic — which is exactly why
     `run_migrations()` below still drives Alembic through an env var (`migrations/env.py`
     constructs its own fresh `Settings()`, per ADR-018 §5) while everything that builds
     an *app* goes through `build_settings()` + `app_client()` instead.
  2. **`ANTHROPIC_BASE_URL` / `GITHUB_API_BASE_URL` are real `Settings` fields**
     (`anthropic_base_url`, `github_api_base_url`), passed explicitly as `base_url=`/a
     path prefix by the adapters — never left to SDK-internal env reading (ADR-017).
     Both carry a loopback-or-canonical guard: a non-canonical value must resolve to
     `localhost`/`127.0.0.0/8`/`::1` or `Settings` refuses to construct. This harness's
     local scripted server binds `127.0.0.1`, so it always satisfies the guard.
  3. **`scripts/seed-owner.py`** is a script context (ADR-018 §3) — env vars +
     `get_settings.cache_clear()` remain the sanctioned pattern there, unlike for the app
     itself. See `test_owner_seed_script_and_login.py`, which owns that seam.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import pytest

from tests._helpers import import_or_fail

TEST_OWNER_USERNAME = "qa-owner"
TEST_OWNER_PASSWORD = "qa-test-password-not-real-Xk9!"
TEST_SESSION_SECRET = "qa-test-session-secret-32-bytes-minimum-000000"
CANARY_ANTHROPIC_KEY = "sk-ant-test-canary-do-not-use-for-real-calls"
CANARY_GITHUB_TOKEN = "github_pat_test-canary-do-not-use-for-real-calls"
WEB_ORIGIN = "http://localhost:3000"


def run_migrations(database_url: str, *, monkeypatch: pytest.MonkeyPatch) -> None:
    """`alembic upgrade head` against an isolated per-test database.

    Alembic is a script context (ADR-018 §3/§5): `migrations/env.py` constructs its own
    fresh `Settings()` reading `DATABASE_URL` from the environment, so driving it via
    `monkeypatch.setenv` (rather than passing a `Settings` object, which Alembic's CLI
    surface has no seam for) is the correct mechanism here, not a leftover shortcut.
    """
    Config = import_or_fail("alembic.config.Config", blocked_on="alembic (installed; should not fire)")
    upgrade = import_or_fail("alembic.command.upgrade", blocked_on="alembic (installed; should not fire)")

    api_root = Path(__file__).resolve().parents[2]  # apps/api/tests/exit/_client.py -> apps/api
    ini_path = api_root / "alembic.ini"
    if not ini_path.exists():
        pytest.fail(
            f"NOT YET BUILT: {ini_path} does not exist yet. Blocked on T2 (data layer, migration 0001).",
            pytrace=False,
        )
    monkeypatch.setenv("DATABASE_URL", database_url)
    cfg = Config(str(ini_path))
    # alembic resolves a relative `script_location` against the process CWD, not
    # against alembic.ini's own directory -- force an absolute path so this works
    # regardless of where `pytest` is invoked from (verified during T18 development).
    script_location = cfg.get_main_option("script_location") or "migrations"
    if not os.path.isabs(script_location):
        cfg.set_main_option("script_location", str((api_root / script_location).resolve()))
    try:
        upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - surfaced deliberately as a clear red failure
        pytest.fail(
            f"NOT YET BUILT or migration failed: `alembic upgrade head` against {ini_path} "
            f"raised {exc.__class__.__name__}: {exc}. Blocked on T2.",
            pytrace=False,
        )


def seed_owner_directly(db_path: Path, *, username: str = TEST_OWNER_USERNAME, password: str = TEST_OWNER_PASSWORD) -> None:
    """Insert the one owner row via a raw SQL INSERT — approved by the Architect
    (docs/M1_BUILD_PLAN.md, "Seeding the owner row in fixtures by raw SQL is approved"),
    using §9.6's format verbatim so it needs nothing from `scripts/seed-owner.py`.
    Requires the `users` table to exist, i.e. must run after `run_migrations`.

    This is deliberately NOT the same code path as `scripts/seed-owner.py` itself —
    that script has its own, separate test in `test_owner_seed_script_and_login.py`,
    which is what the ruling calls out as the previously-uncovered gap.
    """
    import base64
    import hashlib
    import sqlite3
    from datetime import UTC, datetime

    if not db_path.exists():
        pytest.fail(
            f"NOT YET BUILT: {db_path} was not created by run_migrations(). Blocked on T2.",
            pytrace=False,
        )
    n, r, p, dklen = 2**14, 8, 1, 32
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen)
    password_hash = f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, name, username, password_hash, preferences, "
            "security_settings, created_at) VALUES (?, ?, ?, ?, '{}', '{}', ?)",
            (str(uuid4()), "QA Owner", username, password_hash, datetime.now(UTC).isoformat()),
        )
        conn.commit()
    except sqlite3.OperationalError as exc:
        pytest.fail(
            f"NOT YET BUILT: `users` table shape does not match ARCHITECTURE_V1.md §7.3 yet "
            f"({exc}). Blocked on T2.",
            pytrace=False,
        )
    finally:
        conn.close()


def build_settings(
    *,
    database_url: str,
    config_dir: Path,
    anthropic_base_url: str | None = None,
    github_api_base_url: str | None = None,
    turn_deadline_s: int | None = None,
    owner_username: str = TEST_OWNER_USERNAME,
    owner_password: str = TEST_OWNER_PASSWORD,
    anthropic_api_key: str = CANARY_ANTHROPIC_KEY,
    github_token: str = CANARY_GITHUB_TOKEN,
    overrides: dict[str, Any] | None = None,
) -> Any:
    """Construct a fresh `sunil.settings.Settings` instance directly — the ADR-018
    seam. `_env_file=None` so a real repo-root `.env`, if one happens to exist on this
    machine, is never read into a test.

    `anthropic_base_url` / `github_api_base_url` are the ADR-017 transport seams. Every
    value this harness passes for them is loopback (a local `ScriptedHTTPServer`), so
    the accompanying guard (§9.7, T-24) never rejects a legitimate test call — see
    `test_et_settings_base_url_guard.py`'s sibling assertion that it rejects everything
    else.
    """
    Settings = import_or_fail("sunil.settings.Settings", blocked_on="T1 (Settings, ADR-017/018 fields)")
    kwargs: dict[str, Any] = {
        "_env_file": None,
        "database_url": database_url,
        "sunil_config_dir": str(config_dir),
        "anthropic_api_key": anthropic_api_key,
        "github_token": github_token,
        "session_secret": TEST_SESSION_SECRET,
        "web_origin": WEB_ORIGIN,
        "owner_username": owner_username,
        "owner_password": owner_password,
    }
    if anthropic_base_url:
        kwargs["anthropic_base_url"] = anthropic_base_url
    if github_api_base_url:
        kwargs["github_api_base_url"] = github_api_base_url
    if turn_deadline_s is not None:
        kwargs["sunil_turn_deadline_s"] = turn_deadline_s
    if overrides:
        kwargs.update(overrides)

    try:
        return Settings(**kwargs)
    except TypeError as exc:
        pytest.fail(
            f"NOT YET BUILT: sunil.settings.Settings does not yet accept every field "
            f"this harness needs per ADR-017/018 ({exc}). Blocked on T1.",
            pytrace=False,
        )


def build_live_settings(*, database_url: str, config_dir: Path, anthropic_api_key: str, github_token: str) -> Any:
    """Same as `build_settings()`, but for `@pytest.mark.live` tests: real credentials,
    and `anthropic_base_url`/`github_api_base_url` left at their canonical defaults so
    the real APIs are actually called.
    """
    return build_settings(
        database_url=database_url,
        config_dir=config_dir,
        anthropic_api_key=anthropic_api_key,
        github_token=github_token,
    )


@contextmanager
def app_client(*, settings: Any) -> Iterator[Any]:
    """Yield a `fastapi.testclient.TestClient` wrapping `sunil.main.create_app(settings=...)`
    (ADR-018), run inside the client's own context so ASGI lifespan (startup/shutdown)
    actually executes — documented (ARCHITECTURE_V1.md §3.2) to be when the app
    constructs its long-lived httpx/AsyncAnthropic clients from `app.state`.
    """
    create_app = import_or_fail("sunil.main.create_app", blocked_on="T5 (ADR-018 create_app(settings=...) signature)")
    TestClient = import_or_fail("fastapi.testclient.TestClient", blocked_on="fastapi (installed; should not fire)")

    try:
        app = create_app(settings=settings)
    except TypeError as exc:
        pytest.fail(
            f"NOT YET BUILT: sunil.main.create_app() does not yet accept `settings=` "
            f"(ADR-018). Blocked on T5. ({exc})",
            pytrace=False,
        )
    with TestClient(app) as client:
        yield client


def login(client: Any, *, username: str = TEST_OWNER_USERNAME, password: str = TEST_OWNER_PASSWORD) -> None:
    resp = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    if resp.status_code != 200:
        pytest.fail(
            f"NOT YET BUILT or a real defect: POST /api/v1/auth/login returned "
            f"{resp.status_code}: {resp.text[:500]}. Blocked on T5 (auth).",
            pytrace=False,
        )


def post_chat(
    client: Any,
    *,
    message: str,
    request_id: str,
    conversation_id: str | None = None,
) -> Any:
    """POST /api/v1/chat exactly per the frozen contract (docs/M1_BUILD_PLAN.md §6)."""
    return client.post(
        "/api/v1/chat",
        json={"message": message, "conversation_id": conversation_id},
        headers={
            "X-SUNIL-Client": "web",
            "X-Request-Id": request_id,
            "Origin": WEB_ORIGIN,
        },
    )


def new_request_id() -> str:
    return str(uuid4())
