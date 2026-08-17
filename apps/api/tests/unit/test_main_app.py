"""End-to-end tests for `sunil.main.create_app()` and its lifespan (T5).

Unlike `test_routes_auth_health.py` (which deliberately bypasses the
lifespan), these tests run the *real* `create_app()` — real middleware
list, real `lifespan` — against a freshly `alembic upgrade head`-ed
temporary SQLite file and the real, committed `config/` directory. This is
what proves three things together, the way they will actually run:

1. the app refuses to boot against a broken config or an un-migrated
   database (ADR-002 §7.4, ADR-016) — proven by making both fail;
2. `redaction.register_secrets_from_settings()` is called during startup,
   so the redaction mechanism is *live*, not merely built (the DM's
   explicit ask after T4);
3. CORS is outermost and the full middleware stack is wired correctly.

Deliberately **not** `async def` tests: `starlette.testclient.TestClient`
is a synchronous interface (it runs the ASGI app on its own event loop
internally), and Alembic's `command.upgrade()` calls `asyncio.run()` inside
`migrations/env.py` — which raises `RuntimeError: asyncio.run() cannot be
called from a running event loop` if the calling test is itself a
coroutine already running on pytest-asyncio's loop. Plain `def` tests are
correct here, matching `test_migrations.py`'s own pattern.

Every test clears `get_settings`/`get_app_engine`'s `lru_cache` and the
redaction registry, both before and after, so no test's environment or
registered secret can leak into another's — the same L-002-derived
discipline as `test_migrations.py`.
"""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.testclient import TestClient
from sunil.redaction import reset_registry_for_tests, scrub

_API_DIR = Path(__file__).resolve().parents[2]  # apps/api
_ALEMBIC_INI = _API_DIR / "alembic.ini"

_REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-fake-main-app-test",
    "GITHUB_TOKEN": "github_pat_fake-main-app-test",
    "OPENAI_API_KEY": "sk-fake-main-app-test-for-openai",
    "SESSION_SECRET": "fake-session-secret-main-app-test",
    "OWNER_USERNAME": "test-owner",
    "OWNER_PASSWORD": "fake-owner-password-main-app-test",
}


def _clear_caches() -> None:
    from sunil.db.session import get_app_engine
    from sunil.settings import get_settings

    get_settings.cache_clear()
    get_app_engine.cache_clear()


@pytest.fixture(autouse=True)
def _clean_state():
    reset_registry_for_tests()
    _clear_caches()
    yield
    _clear_caches()
    reset_registry_for_tests()


def _set_required_env(monkeypatch: pytest.MonkeyPatch, db_path: Path) -> None:
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    # SUNIL_CONFIG_DIR is left at its default ("./config") deliberately —
    # `paths.resolve_config_dir` falls back to the repository root and
    # finds the real, committed `config/` directory from there.


def _migrate_to_head(db_path: Path) -> None:
    del db_path  # the URL is already set on the environment by the caller
    config = Config(str(_ALEMBIC_INI))
    command.upgrade(config, "head")


def test_app_boots_and_serves_health_against_a_real_migrated_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "main_app_happy.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)

    from sunil.main import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "revision": "0001"}


def test_redaction_registration_is_live_after_startup_not_dormant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The DM's explicit ask: prove `register_secrets_from_settings()` ran
    during the lifespan, rather than trusting that wiring it in was
    enough."""
    db_path = tmp_path / "main_app_redaction.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)

    from sunil.main import create_app

    app = create_app()

    with TestClient(app):
        # Startup has run. The exact secret value this test configured
        # above must now be caught by the shared redaction registry.
        result = scrub(f"the key is {_REQUIRED_ENV['ANTHROPIC_API_KEY']}")

    assert _REQUIRED_ENV["ANTHROPIC_API_KEY"] not in result
    assert "«redacted:anthropic_api_key»" in result


def test_cors_headers_are_present_on_a_normal_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "main_app_cors.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)

    from sunil.main import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"Origin": "http://localhost:3000"})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_a_cors_preflight_for_login_is_answered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "main_app_preflight.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)

    from sunil.main import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,x-sunil-client,x-request-id",
            },
        )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_a_bad_x_request_id_is_rejected_through_the_full_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "main_app_bad_request_id.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)

    from sunil.main import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.get("/api/v1/health", headers={"X-Request-Id": "not-a-valid-uuid4"})

    assert response.status_code == 422


def test_app_refuses_to_boot_against_an_unmigrated_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-002 §7.4: the app must fail closed rather than serve requests
    against a database with no migration applied at all."""
    db_path = tmp_path / "main_app_unmigrated.db"
    _set_required_env(monkeypatch, db_path)
    # Deliberately do NOT migrate — db_path does not even exist yet.

    from sunil.main import create_app

    app = create_app()

    with pytest.raises(Exception):  # noqa: B017 - AlembicHeadMismatch, wrapped by the ASGI lifespan
        with TestClient(app):
            pass


def test_app_refuses_to_boot_against_a_broken_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR-016: a broken/missing config directory must be loud and
    immediate, on the boot path."""
    db_path = tmp_path / "main_app_bad_config.db"
    _set_required_env(monkeypatch, db_path)
    # Set the broken config dir *before* anything calls `get_settings()`
    # for the first time in this test — it is `lru_cache`d, so a change
    # made after the first call would silently have no effect.
    monkeypatch.setenv("SUNIL_CONFIG_DIR", str(tmp_path / "does_not_exist_at_all"))
    _migrate_to_head(db_path)

    from sunil.main import create_app

    app = create_app()

    with pytest.raises(Exception):  # noqa: B017 - RegistryFileError, wrapped by the ASGI lifespan
        with TestClient(app):
            pass


# ---------------------------------------------------------------------------
# ADR-018 — settings/engine/sessionmaker are per-application state, not
# process-global caches. QA's harness builds one app per test, each with its
# own DATABASE_URL; these tests prove that actually works, not just that the
# signature accepts an argument.
# ---------------------------------------------------------------------------


def _hash_password(password: str) -> str:
    salt = b"0123456789ABCDEF"
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


async def _seed_user(db_path: Path, *, username: str, password: str) -> None:
    """Insert one `users` row directly, against an already-migrated
    database file — no app, no lifespan, just the table `alembic upgrade
    head` created."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path.as_posix()}")
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, name, username, password_hash, preferences, "
                "security_settings, created_at) VALUES "
                "(:id, :name, :username, :password_hash, '{}', '{}', :created_at)"
            ),
            {
                "id": f"user-{username}",
                "name": username,
                "username": username,
                "password_hash": _hash_password(password),
                "created_at": "2026-08-14 00:00:00+00:00",
            },
        )
        await session.commit()
    await engine.dispose()


def test_create_app_accepts_explicit_settings_and_stores_them_on_app_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "explicit_settings.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)

    from sunil.main import create_app
    from sunil.settings import Settings

    explicit_settings = Settings(
        _env_file=None,
        **_REQUIRED_ENV,
        DATABASE_URL=f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )

    app = create_app(explicit_settings)

    assert app.state.settings is explicit_settings


def test_create_app_with_no_argument_reads_settings_fresh_ignoring_a_stale_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact regression ADR-018 exists to prevent: `get_settings()` is
    `@lru_cache`d process-wide. If `create_app()` used it, whichever test
    (or whichever app) read settings *first* in this process would pin the
    log level (and, more importantly, the database) for every app built
    afterward — silently."""
    from sunil.settings import get_settings

    first_db = tmp_path / "first.db"
    _set_required_env(monkeypatch, first_db)
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    get_settings()  # primes the process-wide cache with LOG_LEVEL=DEBUG

    second_db = tmp_path / "second.db"
    _set_required_env(monkeypatch, second_db)
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    _migrate_to_head(second_db)

    from sunil.main import create_app

    app = create_app()  # no argument — must not fall back to the stale cache

    assert app.state.settings.log_level == "INFO"
    assert "second.db" in app.state.settings.database_url.get_secret_value()


def test_app_state_engine_and_sessionmaker_are_built_from_this_apps_own_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "engine_check.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)

    from sunil.main import create_app

    app = create_app()

    assert str(app.state.engine.url) == f"sqlite+aiosqlite:///{db_path.as_posix()}"
    session = app.state.sessionmaker()
    assert session.bind is app.state.engine


def test_two_apps_with_different_databases_never_share_a_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The load-bearing proof: `get_session()` must take its sessionmaker
    from *this request's* `app.state`, never from a module-level/cached
    engine — otherwise two apps built with different `DATABASE_URL`s in
    the same process would silently query the same database."""
    import asyncio

    db_a = tmp_path / "app_a.db"
    _set_required_env(monkeypatch, db_a)
    _migrate_to_head(db_a)
    asyncio.run(_seed_user(db_a, username="user-a", password="pass-for-a"))

    from sunil.main import create_app

    app_a = create_app()

    db_b = tmp_path / "app_b.db"
    _set_required_env(monkeypatch, db_b)
    _migrate_to_head(db_b)
    asyncio.run(_seed_user(db_b, username="user-b", password="pass-for-b"))

    app_b = create_app()

    headers = {"X-SUNIL-Client": "web"}
    with TestClient(app_a) as client_a, TestClient(app_b) as client_b:
        # Each app authenticates its own seeded user...
        resp_a_own = client_a.post(
            "/api/v1/auth/login",
            json={"username": "user-a", "password": "pass-for-a"},
            headers=headers,
        )
        resp_b_own = client_b.post(
            "/api/v1/auth/login",
            json={"username": "user-b", "password": "pass-for-b"},
            headers=headers,
        )
        # ...and neither can authenticate the other's user, because they
        # are genuinely different databases, not one shared cached engine.
        resp_a_foreign = client_a.post(
            "/api/v1/auth/login",
            json={"username": "user-b", "password": "pass-for-b"},
            headers=headers,
        )
        resp_b_foreign = client_b.post(
            "/api/v1/auth/login",
            json={"username": "user-a", "password": "pass-for-a"},
            headers=headers,
        )

    assert resp_a_own.status_code == 200
    assert resp_b_own.status_code == 200
    assert resp_a_foreign.status_code == 401
    assert resp_b_foreign.status_code == 401


def test_sunil_main_has_no_module_level_app_attribute() -> None:
    """ADR-018: the module-level `app = create_app()` is deleted — importing
    `sunil.main` must have no side effect, which is what lets a test import
    it before deciding what the environment should say. The run command is
    `uvicorn sunil.main:create_app --factory`."""
    import sunil.main as main_module

    assert not hasattr(main_module, "app")


def test_projects_endpoint_reads_the_real_committed_projects_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end, through the real `create_app()` + lifespan (which calls
    `load_registries()` against the real, committed `config/` directory) —
    not the fake stand-in `test_routes_projects.py` uses. Confirms
    `app.state.registries` is actually what the route reads."""
    db_path = tmp_path / "main_app_projects.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)
    import asyncio

    asyncio.run(_seed_user(db_path, username="isuru", password="fake-password-for-projects"))

    from sunil.main import create_app

    app = create_app()

    with TestClient(app) as client:
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "isuru", "password": "fake-password-for-projects"},
            headers={"X-SUNIL-Client": "web"},
        )
        assert login.status_code == 200

        response = client.get("/api/v1/projects")

    assert response.status_code == 200
    assert response.json() == {
        "projects": [{"key": "easy_clean_workforce", "display_name": "EasyClean Workforce"}]
    }


def test_chat_route_is_registered_on_the_real_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T11b's one-line addition to this module: `chat.router` must be
    mounted, or the endpoint T11a built is unreachable through the real
    app (it is otherwise only exercised by hand-built bare-`FastAPI` route
    tests). A 401 (not 404) proves the route exists and auth-gates it —
    the same shape `test_routes_projects.py` uses for its own route."""
    db_path = tmp_path / "main_app_chat_registered.db"
    _set_required_env(monkeypatch, db_path)
    _migrate_to_head(db_path)

    from sunil.main import create_app

    app = create_app()

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={"message": "hello", "conversation_id": None},
            headers={
                "X-SUNIL-Client": "web",
                "X-Request-Id": "0189d0b3-0000-4000-8000-000000000099",
            },
        )

    assert response.status_code == 401, (
        f"expected 401 (no session) proving the route exists, got {response.status_code}: "
        f"{response.text[:300]}"
    )
