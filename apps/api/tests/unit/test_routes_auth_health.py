"""Route-level tests for `sunil.api.routes.auth` and `.health` (T5).

Deliberately mounts only these two routers on a bare `FastAPI` app with
`get_session` overridden to a fixture in-memory SQLite database — not the
full `sunil.main.create_app()` — so these tests do not need a migrated
database file, `config/*.yaml`, or the lifespan's startup checks. The full
`create_app()` + lifespan path is covered separately in
`test_main_app.py`.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient
from sunil.api.deps import reset_login_throttle_for_tests
from sunil.api.routes import auth, health
from sunil.db.base import Base
from sunil.db.models import User
from sunil.db.session import get_session

_TEST_USERNAME = "isuru"
_TEST_PASSWORD = "a-fake-test-password"


def _hash_password(password: str) -> str:
    salt = b"0123456789ABCDEF"
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


@pytest_asyncio.fixture
async def app_and_client() -> AsyncGenerator[TestClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Not a real `alembic upgrade head` (this fixture is a plain
        # `create_all`) — just enough of an `alembic_version` table for
        # /api/v1/health to have something real to read.
        await conn.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        await conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('0001')")

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    async with sessionmaker() as session:
        session.add(
            User(
                name="Isuru",
                username=_TEST_USERNAME,
                password_hash=_hash_password(_TEST_PASSWORD),
            )
        )
        await session.commit()

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        async with sessionmaker() as s:
            yield s

    app = FastAPI(
        middleware=[
            Middleware(
                SessionMiddleware,
                secret_key="test-only-session-secret",
                session_cookie="sunil_session",
                same_site="lax",
                https_only=False,
            )
        ]
    )
    app.include_router(auth.router)
    app.include_router(health.router)
    app.dependency_overrides[get_session] = override_get_session

    with TestClient(app) as client:
        yield client

    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_throttle():
    reset_login_throttle_for_tests()
    yield
    reset_login_throttle_for_tests()


_HEADERS = {"X-SUNIL-Client": "web"}


# -- POST /api/v1/auth/login --------------------------------------------------


def test_login_with_correct_credentials_returns_the_user_and_a_cookie(
    app_and_client: TestClient,
) -> None:
    response = app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
        headers=_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["name"] == "Isuru"
    assert "id" in body["user"]
    assert "set-cookie" in {k.lower() for k in response.headers.keys()}


def test_login_response_never_carries_the_password_hash(app_and_client: TestClient) -> None:
    response = app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
        headers=_HEADERS,
    )

    assert "password" not in response.text
    assert "scrypt$" not in response.text


def test_login_with_the_wrong_password_is_rejected(app_and_client: TestClient) -> None:
    response = app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": "wrong-password"},
        headers=_HEADERS,
    )

    assert response.status_code == 401


def test_login_without_the_client_header_is_rejected(app_and_client: TestClient) -> None:
    response = app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
    )

    assert response.status_code == 403


def test_six_failed_logins_lock_out_the_account(app_and_client: TestClient) -> None:
    for _ in range(5):
        response = app_and_client.post(
            "/api/v1/auth/login",
            json={"username": _TEST_USERNAME, "password": "wrong-password"},
            headers=_HEADERS,
        )
        assert response.status_code == 401

    locked_response = app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},  # even the right password
        headers=_HEADERS,
    )
    assert locked_response.status_code == 401
    assert "too many" in locked_response.json()["detail"].lower()


# -- GET /api/v1/auth/session --------------------------------------------------


def test_session_reports_unauthenticated_with_no_prior_login(app_and_client: TestClient) -> None:
    response = app_and_client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "user": None}


def test_session_reports_authenticated_after_login(app_and_client: TestClient) -> None:
    app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
        headers=_HEADERS,
    )

    response = app_and_client.get("/api/v1/auth/session")

    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True
    assert body["user"]["name"] == "Isuru"


# -- POST /api/v1/auth/logout --------------------------------------------------


def test_logout_clears_an_authenticated_session(app_and_client: TestClient) -> None:
    app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
        headers=_HEADERS,
    )

    logout_response = app_and_client.post("/api/v1/auth/logout", headers=_HEADERS)
    assert logout_response.status_code == 204

    session_response = app_and_client.get("/api/v1/auth/session")
    assert session_response.json() == {"authenticated": False, "user": None}


def test_logout_without_the_client_header_is_rejected(app_and_client: TestClient) -> None:
    response = app_and_client.post("/api/v1/auth/logout")

    assert response.status_code == 403


# -- GET /api/v1/health --------------------------------------------------------


def test_health_reports_status_ok_and_the_seeded_revision(app_and_client: TestClient) -> None:
    response = app_and_client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "revision": "0001"}


def test_health_requires_no_authentication(app_and_client: TestClient) -> None:
    """Liveness must be checkable before anyone has logged in."""
    response = app_and_client.get("/api/v1/health")

    assert response.status_code == 200
