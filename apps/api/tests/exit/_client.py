"""Builds a real, running SUNIL app for exit tests, plus the thin HTTP helpers every
exit test shares — written against the frozen docs/M1_BUILD_PLAN.md §6 contract only.

Every function here is a PLAIN function (never a `@pytest.fixture`); call these from
inside a test's own body so a missing module surfaces as a FAILED test, not a
collection/fixture-setup ERROR — see tests/_helpers.py's docstring for why that
distinction is the whole point of this harness being "red for the right reason".

ASSUMPTIONS made here, all named again in the T18 report (search that report for
"Ambiguity" to see the full reasoning):

  1. `sunil.main.create_app()` takes no arguments and reads Settings fresh from the
     process environment each call. If Settings is a process-wide `lru_cache`d
     singleton instead, tests run in the same pytest session may cross-contaminate
     each other's DATABASE_URL/mock-server port — not a false pass (everything here
     still fails at `import_or_fail` today), but a real risk once T1 lands. Flagged,
     not guessed around.
  2. `apps/api/alembic.ini` + `apps/api/migrations/` (T2) exist and read `DATABASE_URL`
     from the environment at upgrade time — the standard alembic convention, and the
     one ARCHITECTURE_V1.md §7.1 implies ("DATABASE_URL switches between them").
  3. The owner user row can be seeded directly with a raw SQL INSERT using exactly the
     scrypt encoding ARCHITECTURE_V1.md §9.6 specifies verbatim
     (`scrypt$n$r$p$salt_b64$hash_b64`, n=2**14, r=8, p=1, dklen=32), so these tests do
     not also need to guess `scripts/seed-owner.py`'s CLI/env interface.
  4. GitHub tool calls can be redirected to a local double via `GITHUB_API_BASE_URL` —
     NOT a documented env var today (only `ANTHROPIC_BASE_URL` is verified — see
     `_mock_upstreams.py`). QA requests this as a two-line addition to T8.

VERIFIED (not assumed): `run_migrations` below was exercised end to end against a
throwaway, QA-authored alembic scaffold (a trivial `users`-only migration) during T18
development to confirm the whole chain -- migrate, seed, hit the next real blocker --
actually advances correctly. That scaffold was then deleted; it is not part of this
harness and never depended on any `sunil` code, so it proves nothing about the real
schema, only that this file's own logic is sound. See the T18 report for the transcript.
"""

from __future__ import annotations

import base64
import hashlib
import os
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tests._helpers import import_or_fail

TEST_OWNER_ID = "00000000-0000-4000-8000-000000000001"
TEST_OWNER_USERNAME = "qa-owner"
TEST_OWNER_PASSWORD = "qa-test-password-not-real-Xk9!"
TEST_SESSION_SECRET = "qa-test-session-secret-32-bytes-minimum-000000"
WEB_ORIGIN = "http://localhost:3000"


def _scrypt_encode(password: str) -> str:
    """Exactly ARCHITECTURE_V1.md §9.6's format: scrypt$n$r$p$salt_b64$hash_b64."""
    n, r, p, dklen = 2**14, 8, 1, 32
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen
    )
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def run_migrations(database_url: str, *, monkeypatch: pytest.MonkeyPatch) -> None:
    """`alembic upgrade head` against an isolated per-test database. See module
    docstring assumption 2."""
    Config = import_or_fail(
        "alembic.config.Config", blocked_on="alembic (installed; should not fire)"
    )
    upgrade = import_or_fail(
        "alembic.command.upgrade", blocked_on="alembic (installed; should not fire)"
    )

    api_root = (
        Path(__file__).resolve().parents[2]
    )  # apps/api/tests/exit/_client.py -> apps/api
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
    # regardless of where `pytest` is invoked from (verified during T18 development;
    # see the module docstring).
    script_location = cfg.get_main_option("script_location") or "migrations"
    if not os.path.isabs(script_location):
        cfg.set_main_option(
            "script_location", str((api_root / script_location).resolve())
        )
    try:
        upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - surfaced deliberately as a clear red failure
        pytest.fail(
            f"NOT YET BUILT or migration failed: `alembic upgrade head` against {ini_path} "
            f"raised {exc.__class__.__name__}: {exc}. Blocked on T2.",
            pytrace=False,
        )


def seed_owner(db_path: Path) -> None:
    """Insert the one owner row directly (module docstring assumption 3) — requires
    the `users` table to exist, i.e. must run after `run_migrations`."""
    if not db_path.exists():
        pytest.fail(
            f"NOT YET BUILT: {db_path} was not created by run_migrations(). Blocked on T2.",
            pytrace=False,
        )
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO users (id, name, username, password_hash, preferences, "
            "security_settings, created_at) VALUES (?, ?, ?, ?, '{}', '{}', ?)",
            (
                TEST_OWNER_ID,
                "QA Owner",
                TEST_OWNER_USERNAME,
                _scrypt_encode(TEST_OWNER_PASSWORD),
                datetime.now(UTC).isoformat(),
            ),
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


def _base_env(*, database_url: str, config_dir: Path) -> dict[str, str]:
    """Every value here is a documented, placeholder-shaped entry from
    ARCHITECTURE_V1.md §14.4 — never a real secret (ET-10 territory)."""
    return {
        "DATABASE_URL": database_url,
        "SUNIL_CONFIG_DIR": str(config_dir),
        "ANTHROPIC_API_KEY": "sk-ant-test-canary-do-not-use-for-real-calls",
        "GITHUB_TOKEN": "github_pat_test-canary-do-not-use-for-real-calls",
        "SESSION_SECRET": TEST_SESSION_SECRET,
        "SESSION_COOKIE_NAME": "sunil_session",
        "WEB_ORIGIN": WEB_ORIGIN,
        "API_HOST": "localhost",
        "API_PORT": "8000",
        "LOG_LEVEL": "INFO",
        "SUNIL_PROGRESS_EVENTS": "false",
        "SUNIL_TURN_DEADLINE_S": "40",
        "OWNER_USERNAME": TEST_OWNER_USERNAME,
        "OWNER_PASSWORD": TEST_OWNER_PASSWORD,
        "NEXT_PUBLIC_API_BASE_URL": "http://localhost:8000",
    }


@contextmanager
def app_client(
    *,
    database_url: str,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    anthropic_base_url: str | None = None,
    github_api_base_url: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> Iterator[Any]:
    """Yield a `fastapi.testclient.TestClient` wrapping a freshly-constructed
    `sunil.main.create_app()`, run inside the client's own context so ASGI lifespan
    (startup/shutdown) actually executes — that is documented (ARCHITECTURE_V1.md §3.2)
    to be when the app constructs its long-lived httpx/AsyncAnthropic clients, which is
    exactly what must happen for `ANTHROPIC_BASE_URL` to have already been set.
    """
    env = _base_env(database_url=database_url, config_dir=config_dir)
    if anthropic_base_url:
        env["ANTHROPIC_BASE_URL"] = anthropic_base_url
    if github_api_base_url:
        env["GITHUB_API_BASE_URL"] = (
            github_api_base_url  # requested addition — see module docstring
        )
    if extra_env:
        env.update(extra_env)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    create_app = import_or_fail(
        "sunil.main.create_app", blocked_on="T1 (app factory) + T5 (API skeleton)"
    )
    TestClient = import_or_fail(
        "fastapi.testclient.TestClient",
        blocked_on="fastapi (installed; should not fire)",
    )

    app = create_app()
    with TestClient(app) as client:
        yield client


def login(client: Any) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username": TEST_OWNER_USERNAME, "password": TEST_OWNER_PASSWORD},
    )
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
    return str(uuid.uuid4())
