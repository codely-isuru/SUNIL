"""A written memory is recalled into the NEXT turn — against the real provider.

This is `test_governed_turn.py`'s governed turn, unchanged, with one seam
swapped: `SUNIL_MEMORY_PROVIDER`'s real `PgVectorMemoryProvider` on a live
Postgres replaces C3 §5's fake. The module-level `memory` fixture overrides the
conftest one, so `app_client` — the same real app, the same real owner session,
the same real Tool Manager — wires the real provider without a line of it
changing. That is the claim worth testing: the orchestrator's context loading
is unchanged in shape and cannot tell which engine is behind the seam.

The evidence is taken at two depths, because only one of them is a fact about
the assistant:

1. **the trace** — stage 3 `memory_retrieved` reports `items: 1` and
   `degraded: false`, which is what an operator reading `audit_events` sees;
2. **the prompt** — the recalled content actually appears in the analysis call
   the provider received, as `[recalled memory] …`. A trace saying "1 item"
   while the prompt carried none would be a turn that logged remembering and did
   not remember, and (1) alone cannot tell the two apart.

Skips loudly without Postgres, for `tests/unit/memory/factory.py`'s reason: a
vector recall SQLite cannot run would pass against nothing.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
import pytest_asyncio
from sqlalchemy import select

from sunil.core.memory.provider import MemoryItem, MemoryScope, WriteRules
from sunil.core.memory.service import MemoryService
from sunil.db.models import AuditEvent, User
from tests.unit.memory import factory
from tests.unit.memory.factory import requires_postgres

pytestmark = requires_postgres

WEB_HEADERS = {"X-SUNIL-Client": "web", "Origin": "http://localhost:3001"}


@pytest.fixture(scope="session")
def event_loop_policy():
    """psycopg 3's async mode refuses Windows' default `ProactorEventLoop`, and
    `postgresql+psycopg` is ARCHITECTURE_V2 §5's normative driver. Without this
    the Postgres leg errors out on a Windows build machine and the suite looks
    green — see `tests/unit/memory/conftest.py` for the full note."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


@pytest_asyncio.fixture
async def pg_engine():
    url = factory.postgres_url()
    assert url is not None  # guarded by `requires_postgres`
    async for engine in factory.engine_for(url):
        yield engine


@pytest_asyncio.fixture
async def memory(request, pg_engine):
    """Overrides `tests/integration/conftest.py`'s `FakeMemoryProvider`.

    Its own engine, not the app's: the spine runs on in-memory SQLite here (the
    harness's choice, ADR-001's portable schema) while long-term memory needs
    pgvector. In a deployment both are the one Postgres — `wiring.py` hands the
    provider the application's engine, and `tests/unit/memory/test_wiring.py`
    pins that.

    `indirect=True` with `"dead"` swaps in a provider whose database is
    unreachable, which is how the degrade test gets a REAL failure rather than a
    mocked one.
    """
    if getattr(request, "param", "live") == "dead":
        return factory.dead_provider()
    return factory.make_provider(pg_engine)


def memory_item(content: str) -> MemoryItem:
    return MemoryItem(
        content=content,
        memory_type="fact",
        privacy="internal",
        source_request_id="req-seed",
    )


async def _turn_scope(app_client, conversation_id: str) -> MemoryScope:
    """The scope the turn itself will recall against.

    Read from the database rather than assumed: `memory_scope_for_turn` keys on
    the SESSION's user id (a uuid), and only its machine-lane fallback is the
    literal `"owner"`. A test that hard-coded `"owner"` would write into a scope
    no cookie-lane turn ever reads — and would then "prove" recall by finding
    nothing, since a scope miss and an empty store look identical from here.
    """
    _, app = app_client
    async with app.state.sessionmaker() as session:
        user = (
            await session.execute(select(User).where(User.username == "owner"))
        ).scalar_one()
    return MemoryScope(user_id=user.id, kind="conversation", id=conversation_id)


async def _stage(app_client, request_id: str, stage: str) -> AuditEvent:
    """One stage row of ONE turn, from `audit_events` — the durable trace, not
    the response envelope's copy of it. Keyed on `request_id` so a second turn's
    row can never be read as the first's."""
    _, app = app_client
    async with app.state.sessionmaker() as session:
        row = (
            await session.execute(
                select(AuditEvent).where(
                    AuditEvent.request_id == request_id, AuditEvent.stage == stage
                )
            )
        ).scalar_one()
    return row


async def test_a_written_memory_is_recalled_into_the_next_turn(
    app_client, memory, provider
) -> None:
    """The Stream C exit criterion, in one test: something remembered in an
    earlier turn reaches the next turn's prompt, with the recall visible in the
    trace."""
    client, app = app_client

    # Turn 1 — establishes the conversation whose scope the memory is filed in.
    first = await client.post(
        "/api/v1/chat",
        json={"message": "PLAN: write the demo item"},
        headers=WEB_HEADERS,
    )
    assert first.status_code == 200, first.text
    conversation_id = first.json()["conversation_id"]

    # Something worth remembering, written through the SERVICE — so the audit
    # row is minted before the vendor call and its id comes back in the receipt,
    # which is the whole of C3 §2's audit-outside-vendor rule.
    class Sink:
        def __init__(self) -> None:
            self.rows: list[str] = []

        async def record_memory_write(self, *, scope, item) -> str:
            self.rows.append(f"audit-mem-{len(self.rows) + 1}")
            return self.rows[-1]

    sink = Sink()
    service = MemoryService(memory, audit_sink=sink)
    receipt = await service.write(
        memory_item("The owner signed off the winch recovery scope on Tuesday"),
        WriteRules(capture="redacted_full"),
        scope=await _turn_scope(app_client, conversation_id),
    )
    assert receipt.op == "created"
    assert receipt.audit_event_id == sink.rows[-1]

    provider.calls.clear()

    # Turn 2 — the same conversation, a question whose words overlap the memory.
    second = await client.post(
        "/api/v1/chat",
        json={
            "message": "PLAN: what did the owner sign off about winch recovery scope?",
            "conversation_id": conversation_id,
        },
        headers=WEB_HEADERS,
    )
    assert second.status_code == 200, second.text

    # (1) the trace — what an operator reading `audit_events` sees.
    retrieved = await _stage(app_client, second.json()["request_id"], "memory_retrieved")
    assert retrieved.detail["items"] == 1
    assert retrieved.detail["degraded"] is False
    assert retrieved.detail["reason"] == "none"

    # (2) the prompt — the recall actually reached the model call.
    recalled_lines = [
        message.content
        for call in provider.calls
        for message in call.messages
        if message.content.startswith("[recalled memory]")
    ]
    assert recalled_lines
    assert any("winch recovery scope on Tuesday" in line for line in recalled_lines)


async def test_a_memory_from_another_conversation_is_not_recalled(
    app_client, memory, provider
) -> None:
    """The leak probe, at turn level. A provider that filed by nothing would
    pass the test above and fail this one — which is why both are here."""
    client, _ = app_client

    first = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )
    other_conversation = first.json()["conversation_id"]

    service = MemoryService(memory)
    await service.write(
        memory_item("A secret about winch recovery from a different conversation"),
        WriteRules(capture="redacted_full"),
        scope=await _turn_scope(app_client, other_conversation),
        audit_event_id="audit-elsewhere",
    )

    provider.calls.clear()
    second = await client.post(
        "/api/v1/chat",
        json={"message": "PLAN: tell me about winch recovery"},
        headers=WEB_HEADERS,
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversation_id"] != other_conversation

    retrieved = await _stage(app_client, second.json()["request_id"], "memory_retrieved")
    assert retrieved.detail["items"] == 0

    assert not [
        message
        for call in provider.calls
        for message in call.messages
        if message.content.startswith("[recalled memory]")
    ]


@pytest.mark.parametrize("memory", ["dead"], indirect=True)
async def test_the_turn_degrades_rather_than_fails_when_memory_is_down(
    app_client, memory
) -> None:
    """C3 §2's rule at turn level, against the REAL provider's real failure:
    memory being down DEGRADES a turn, it never fails one. The owner still gets
    an answer, and the trace records that it was composed without long-term
    memory."""
    client, _ = app_client

    response = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )

    assert response.status_code == 200, response.text
    assert response.json()["outcome"] == "ok"

    retrieved = await _stage(app_client, response.json()["request_id"], "memory_retrieved")
    assert retrieved.detail["degraded"] is True
    assert retrieved.detail["items"] == 0
    assert retrieved.detail["reason"] in ("unavailable", "budget_exceeded")
