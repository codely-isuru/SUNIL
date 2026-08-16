"""Route-level tests for `sunil.api.routes.projects` (T5).

Mounts `auth.router` (to establish a real session the normal way — login)
and `projects.router` on a bare `FastAPI` app, with `get_session`
overridden to a fixture in-memory database and `app.state.registries` set
to a lightweight stand-in exposing the same `.projects.known_projects()`
shape `core/registry/loader.Registries` does — this test is scoped to the
route's own responsibility (auth-gating, reading `app.state.registries`,
shaping the response), not to re-testing T3's registry loader.
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
from sunil.api.routes import auth, projects
from sunil.db.base import Base
from sunil.db.models import User
from sunil.db.session import get_session

_TEST_USERNAME = "isuru"
_TEST_PASSWORD = "a-fake-test-password"

_KNOWN_PROJECTS = [
    {"key": "easy_clean_workforce", "display_name": "EasyClean Workforce"},
]


def _hash_password(password: str) -> str:
    salt = b"0123456789ABCDEF"
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt$16384$8$1${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


class _FakeProjectRegistry:
    def __init__(self, known: list[dict[str, str]]) -> None:
        self._known = known

    def known_projects(self) -> list[dict[str, str]]:
        return self._known


class _FakeRegistries:
    def __init__(self, known: list[dict[str, str]]) -> None:
        self.projects = _FakeProjectRegistry(known)


@pytest_asyncio.fixture
async def app_and_client() -> AsyncGenerator[TestClient]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

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
    app.include_router(projects.router)
    app.dependency_overrides[get_session] = override_get_session
    app.state.registries = _FakeRegistries(_KNOWN_PROJECTS)

    with TestClient(app) as client:
        yield client

    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_throttle():
    reset_login_throttle_for_tests()
    yield
    reset_login_throttle_for_tests()


def test_projects_requires_authentication(app_and_client: TestClient) -> None:
    response = app_and_client.get("/api/v1/projects")

    assert response.status_code == 401


def test_projects_returns_the_known_projects_shape_once_authenticated(
    app_and_client: TestClient,
) -> None:
    login = app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
        headers={"X-SUNIL-Client": "web"},
    )
    assert login.status_code == 200

    response = app_and_client.get("/api/v1/projects")

    assert response.status_code == 200
    assert response.json() == {"projects": _KNOWN_PROJECTS}


def test_projects_element_shape_matches_failure_known_projects(
    app_and_client: TestClient,
) -> None:
    """The frozen §6 contract's `failure.known_projects` uses
    `{key, display_name}` — this endpoint must produce exactly that
    element shape, not a superset or a rename, so the frontend can render
    both from one component."""
    app_and_client.post(
        "/api/v1/auth/login",
        json={"username": _TEST_USERNAME, "password": _TEST_PASSWORD},
        headers={"X-SUNIL-Client": "web"},
    )

    response = app_and_client.get("/api/v1/projects")

    body = response.json()
    assert set(body["projects"][0].keys()) == {"key", "display_name"}
