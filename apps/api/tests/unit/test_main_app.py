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

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from starlette.testclient import TestClient
from sunil.redaction import reset_registry_for_tests, scrub

_API_DIR = Path(__file__).resolve().parents[2]  # apps/api
_ALEMBIC_INI = _API_DIR / "alembic.ini"

_REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-fake-main-app-test",
    "GITHUB_TOKEN": "github_pat_fake-main-app-test",
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
