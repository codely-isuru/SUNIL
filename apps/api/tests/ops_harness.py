"""The request harness for the C6 ops-read routes — the shape C6 §6 deliberately
does NOT fix (it fixes the assertions, not how a test reaches a route).

It lives OUTSIDE ``tests/contracts/`` on purpose. ``tests/contracts`` is QA's
frozen deliverable; the integration round's only licensed edit there is the three
commissioned stub bodies of C6 test 9, so anything those bodies need that is not
an assertion belongs in a module the implementation lane owns. It is shared
rather than duplicated so the contract clauses and the wiring unit tests reach
the routes through exactly one definition of "a signed-in owner".

Everything below is the REAL application: ``sunil.main.create_app``, the real
session middleware, the real ``POST /api/v1/auth/login`` (so the cookie is
genuinely minted and signed by ADR-007's machinery rather than forged here — a
forged cookie would prove the routes accept a value the app never issued), the
real auth dependencies and the real route table. Only the four frozen-contract
seams are fakes, because the auth posture under test is upstream of all of them.

SQLite is the unit-suite posture (ADR-001's one portable schema, ARCHITECTURE_V2
§1): these are route tests and a Postgres daemon would make the contract suite
unrunnable on a clean checkout.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

#: The repo-root `config/` the registry loaders read (ADR-016: mounted, never
#: baked). Resolved from THIS file, never from the process's working directory.
CONFIG_DIR = str(Path(__file__).resolve().parents[3] / "config")

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "not-a-real-password"

#: A test-only value. Never a real secret, and never written to `.env`.
SERVICE_TOKEN = "svc-token-0123456789-abcdefghij"

WEB_ORIGIN = "http://localhost:3001"
WEB_HEADERS = {"X-SUNIL-Client": "web", "Origin": WEB_ORIGIN}

#: The five C6 operations, as paths (C6 OpenAPI `paths`). Kept here so the
#: wiring tests and the contract clauses walk the same list.
C6_PATHS = [
    "/api/v1/tasks",
    "/api/v1/tasks/{task_id}",
    "/api/v1/activity",
    "/api/v1/audit",
    "/api/v1/audit/{request_id}",
]


def build_ops_app(*, service_token: str | None = None, approvals=None, **overrides):
    """The real `create_app` with the frozen fakes wired. Returns `(app, sessionmaker)`.

    Synchronous, so the request-free route-table walks can use it too.
    `approvals` replaces C4 §6's fake for the tests that need a service with a
    schedule; every other keyword is a `Settings` field.
    """
    from sunil.api.wiring import Seams
    from sunil.db.base import Base
    from sunil.main import create_app
    from sunil.settings import Settings

    from tests.fakes.fake_approvals import FakeApprovalsService
    from tests.fakes.fake_memory_provider import FakeMemoryProvider
    from tests.fakes.fake_provider import FakeProvider

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    settings = Settings(
        _env_file=None,
        session_secret="test-session-secret-not-a-real-key",
        sunil_config_dir=CONFIG_DIR,
        sunil_memory_provider="fake",
        sunil_tool_manager="fake",
        sunil_approvals_service="fake",
        sunil_llm_provider_lane="fake",
        sunil_service_token=service_token,
        web_origin=WEB_ORIGIN,
        **overrides,
    )
    app = create_app(
        settings,
        seams=Seams(
            sessionmaker=sessionmaker,
            provider=FakeProvider(),
            memory_provider=FakeMemoryProvider(),
            approvals=approvals if approvals is not None else FakeApprovalsService(),
            # Never reached by an ops read; present because a `fake` seam
            # selection must be injected rather than defaulted (wiring.py rule 1).
            tool_manager=lambda audit_hook: None,
        ),
    )
    app.state.schema_base = Base
    return app, sessionmaker


@asynccontextmanager
async def ops_client(
    *, service_token: str | None = None, sign_in: bool = True
) -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    """The real app over an in-process ASGI transport, yielding `(client, app)`.

    `sign_in=False` yields a client that holds NO session cookie — the no-session
    clause of C6 test 9 must be driven by the genuine absence of a cookie, not by
    deleting one after the fact.
    """
    from sunil.api.routes.auth import hash_password
    from sunil.db.base import Base, new_uuid
    from sunil.db.models import User

    app, sessionmaker = build_ops_app(service_token=service_token)
    engine = sessionmaker.kw["bind"]
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with sessionmaker() as session:
        session.add(
            User(
                id=new_uuid(),
                name="Owner",
                username=OWNER_USERNAME,
                password_hash=hash_password(OWNER_PASSWORD),
            )
        )
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        if sign_in:
            signed_in = await client.post(
                "/api/v1/auth/login",
                json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
                headers=WEB_HEADERS,
            )
            assert signed_in.status_code == 200, signed_in.text
        yield client, app
    await engine.dispose()
