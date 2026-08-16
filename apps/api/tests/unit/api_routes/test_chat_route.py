"""Route-level tests for `POST /api/v1/chat` (T11a), against
`StubTurnExecutor` — T11b wires in the real one without this file
changing. Mirrors `test_routes_auth_health.py`'s own pattern: a bare
`FastAPI` app carrying only the middleware/router under test, with
`get_session` overridden to an in-memory fixture database, rather than
the full `sunil.main.create_app()`.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.middleware import Middleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import Response
from starlette.testclient import TestClient
from sunil.api.middleware import RequestContextMiddleware
from sunil.api.routes import chat
from sunil.db.base import Base
from sunil.db.models import User
from sunil.db.session import get_session

_TEST_USER_ID = "user-1"


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
                id=_TEST_USER_ID,
                name="Test Owner",
                username="test-owner",
                password_hash="scrypt$16384$8$1$fake$fake",
                preferences={},
                security_settings={},
            )
        )
        await session.commit()

    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        async with sessionmaker() as s:
            yield s

    app = FastAPI(
        middleware=[
            Middleware(RequestContextMiddleware),
            Middleware(
                SessionMiddleware,
                secret_key="test-only-session-secret",
                session_cookie="sunil_session",
                same_site="lax",
                https_only=False,
            ),
        ]
    )
    app.include_router(chat.router)

    # A test-only login stand-in: sets `request.session["user_id"]`
    # exactly as the real `/auth/login` handler does, without needing
    # the whole auth router (and its password machinery) mounted here.
    @app.post("/test-only/login-as")
    async def _login_as(request: Request) -> Response:
        request.session["user_id"] = _TEST_USER_ID
        return Response(status_code=204)

    app.dependency_overrides[get_session] = override_get_session
    # ADR-018: request-path code reads these from app.state, never a
    # module-level cache -- set directly here since this fixture builds
    # its own bare app rather than going through create_app().
    app.state.sessionmaker = sessionmaker

    class _FakeSettings:
        sunil_turn_deadline_s = 40

    app.state.settings = _FakeSettings()

    with TestClient(app) as client:
        yield client


def _login(client: TestClient) -> None:
    resp = client.post("/test-only/login-as")
    assert resp.status_code == 204


def _headers(request_id: str) -> dict[str, str]:
    return {"X-SUNIL-Client": "web", "X-Request-Id": request_id}


def test_chat_requires_a_session(app_and_client: TestClient) -> None:
    resp = app_and_client.post(
        "/api/v1/chat",
        json={"message": "hello", "conversation_id": None},
        headers=_headers("0189d0b3-0000-4000-8000-000000000001"),
    )

    assert resp.status_code == 401


def test_chat_rejects_a_missing_client_header(app_and_client: TestClient) -> None:
    _login(app_and_client)

    resp = app_and_client.post(
        "/api/v1/chat",
        json={"message": "hello", "conversation_id": None},
        headers={"X-Request-Id": "0189d0b3-0000-4000-8000-000000000002"},
    )

    assert resp.status_code == 403


def test_chat_rejects_a_malformed_request_id(app_and_client: TestClient) -> None:
    _login(app_and_client)

    resp = app_and_client.post(
        "/api/v1/chat",
        json={"message": "hello", "conversation_id": None},
        headers={"X-SUNIL-Client": "web", "X-Request-Id": "not-a-uuid"},
    )

    assert resp.status_code == 422


def test_chat_rejects_an_empty_message_body(app_and_client: TestClient) -> None:
    _login(app_and_client)

    resp = app_and_client.post(
        "/api/v1/chat",
        json={"message": "", "conversation_id": None},
        headers=_headers("0189d0b3-0000-4000-8000-000000000003"),
    )

    assert resp.status_code == 422


def test_chat_rejects_a_message_over_8000_characters(app_and_client: TestClient) -> None:
    _login(app_and_client)

    resp = app_and_client.post(
        "/api/v1/chat",
        json={"message": "x" * 8001, "conversation_id": None},
        headers=_headers("0189d0b3-0000-4000-8000-000000000004"),
    )

    assert resp.status_code == 422


def test_chat_returns_the_frozen_envelope_shape_on_the_stub_rejection(
    app_and_client: TestClient,
) -> None:
    _login(app_and_client)

    resp = app_and_client.post(
        "/api/v1/chat",
        json={"message": "Check on Sample Project.", "conversation_id": None},
        headers=_headers("0189d0b3-0000-4000-8000-000000000005"),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["request_id"] == "0189d0b3-0000-4000-8000-000000000005"
    assert body["conversation_id"]
    assert body["outcome"] == "failed"
    assert body["message"] is None
    assert body["task"] is None
    assert body["failure"] == {"kind": "plan_rejected", "known_projects": None}
    assert body["usage"] == {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    assert isinstance(body["trace"], list)


def test_chat_response_carries_all_twelve_stages_in_order(app_and_client: TestClient) -> None:
    """ET-6's own shape, verified even for the stub's failure path — every
    stage this branch's pipeline can reach (1, 2, 3, 12) must appear, and
    in `TRACE_STAGES` order relative to each other."""
    _login(app_and_client)

    resp = app_and_client.post(
        "/api/v1/chat",
        json={"message": "hello", "conversation_id": None},
        headers=_headers("0189d0b3-0000-4000-8000-000000000006"),
    )

    stages = [entry["stage"] for entry in resp.json()["trace"]]
    assert stages == ["message_received", "context_loaded", "memory_retrieved", "final_response"]


def test_chat_rejects_an_unknown_conversation_id_with_422(app_and_client: TestClient) -> None:
    _login(app_and_client)

    resp = app_and_client.post(
        "/api/v1/chat",
        json={"message": "hello", "conversation_id": "does-not-exist"},
        headers=_headers("0189d0b3-0000-4000-8000-000000000007"),
    )

    assert resp.status_code == 422
