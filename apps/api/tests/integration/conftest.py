"""Fixtures for the integration suite only — see `tests/unit/conftest.py` for
why they are imported by name and not registered as a plugin.

`app_client` builds the REAL application against the frozen fakes: C2 §5's
`FakeProvider`, C1 §6.3's `FakeToolAdapter` behind §6.1's `FakePermissionHook`,
C4 §6's `FakeApprovalsService`, and C3 §5's `FakeMemoryProvider`. The single
double is the Tool Manager (`tool_manager_double.py` explains why the spine must
not write the chokepoint).

The owner session is REAL: the fixture seeds a `users` row and signs in through
`POST /api/v1/auth/login`, so every turn below runs behind the same cookie +
`X-SUNIL-Client` + Origin controls a browser faces. A test that faked the session
would prove the turn works for a caller who was never authenticated.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from sunil.api.routes.auth import hash_password
from sunil.api.wiring import Seams
from sunil.core.audit.hooks import DbToolAuditHook
from sunil.db.base import new_uuid
from sunil.db.models import User
from sunil.main import create_app

from tests.fakes.fake_approvals import FakeApprovalsService
from tests.fakes.fake_hooks import FakePermissionHook
from tests.fakes.fake_memory_provider import FakeMemoryProvider
from tests.fakes.fake_provider import FakeProvider
from tests.fakes.fake_tool_adapter import FakeToolAdapter
from tests.integration.tool_manager_double import ToolManagerDouble
from tests.spine_harness import (  # noqa: F401 - re-exported as fixtures
    _clean_redaction_registry,
    build_settings,
    session_factory,
)

#: The repo-root `config/` the registry loaders read (ADR-016: mounted, never
#: baked). Resolved from THIS file, never from the process's working directory,
#: so the suite gives the same answer wherever pytest was invoked from.
CONFIG_DIR = str(Path(__file__).resolve().parents[4] / "config")

OWNER_USERNAME = "owner"
OWNER_PASSWORD = "not-a-real-password"
WEB_HEADERS = {"X-SUNIL-Client": "web", "Origin": "http://localhost:3001"}


@pytest.fixture
def adapter() -> FakeToolAdapter:
    return FakeToolAdapter()


@pytest.fixture
def permissions() -> FakePermissionHook:
    """Default-deny with one explicit grant: the turn under test is governed, not
    permitted by omission. Tests that want the deny or ask_user lane clear this
    and re-grant."""
    hook = FakePermissionHook()
    hook.grant("project_manager", "fake_tool", "write_item", "allow")
    return hook


@pytest.fixture
def approvals() -> FakeApprovalsService:
    return FakeApprovalsService()


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def memory() -> FakeMemoryProvider:
    return FakeMemoryProvider()


@pytest_asyncio.fixture
async def app_client(
    session_factory,  # noqa: F811 - the harness fixture
    adapter: FakeToolAdapter,
    permissions: FakePermissionHook,
    approvals: FakeApprovalsService,
    provider: FakeProvider,
    memory: FakeMemoryProvider,
) -> AsyncIterator[tuple[httpx.AsyncClient, object]]:
    """The real app + a signed-in owner, over an in-process ASGI transport."""

    def tool_manager_factory(audit_hook: DbToolAuditHook) -> ToolManagerDouble:
        """C1 §2.1's constructor shape. The manager is built PER PLAN EXECUTION
        because its audit hook is bound to that plan's id (ADR-004 Amendment 1) —
        when Stream A's `ToolManager` lands, this line becomes
        `ToolManager(adapters, permission_hook, approvals, audit_hook)` and
        nothing else here changes."""
        return ToolManagerDouble([adapter], permissions, approvals, audit_hook)

    settings = build_settings(sunil_config_dir=CONFIG_DIR)
    app = create_app(
        settings,
        seams=Seams(
            sessionmaker=session_factory,
            provider=provider,
            memory_provider=memory,
            approvals=approvals,
            tool_manager=tool_manager_factory,
            tool_adapters=(adapter,),
        ),
    )

    async with session_factory() as session:
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
        login = await client.post(
            "/api/v1/auth/login",
            json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
            headers=WEB_HEADERS,
        )
        assert login.status_code == 200, login.text
        yield client, app
