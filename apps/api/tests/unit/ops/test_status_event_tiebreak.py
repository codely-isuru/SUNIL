"""C6 §2.2's "ties keep write order", graded against the SPINE's real schema.

The C6 suite (``test_c6_ops_reads.py``) seeds ``ops_read_model.OPS_METADATA`` —
Stream D's private transcription of the spine's tables, where
``task_status_events.id`` is ``Integer, autoincrement=True``. Production reads
the tables ``db/models.py`` declares. While those two disagreed about the id's
TYPE, every C6 test was green and the contract sentence they exist to defend was
false in production: ``TaskDetail.status_events`` promises "Ascending ``at`` (a
timeline); **ties keep write order**", the route implements that as
``ORDER BY at ASC, id ASC``, and a random UUID id orders by nothing at all.

So this module seeds the SPINE schema and drives the real route over it. It is
the regression test for the integration-w1 §5.2 disposition; against
``id = String(36), default=uuid4`` the first test fails for all but one of the
720 possible orderings and the second fails outright.

``id`` itself is not on C6's wire (``TaskStatusEvent.required`` is
``[from_status, to_status, at]``), which is what leaves the type free to be
chosen for the ordering job the contract actually gives it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from sunil.api.routes import tasks as tasks_routes
from sunil.api.routes.approvals import CLIENT_HEADER, CLIENT_VALUE, install_error_handlers
from sunil.db.base import Base
from sunil.db.models import Conversation, Task, TaskStatusEvent

AUTH = {CLIENT_HEADER: CLIENT_VALUE}

#: One instant, shared by every event — so `at` cannot break any tie and the
#: id is the only thing left that can.
TIED_AT = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

#: Written in this order. Not alphabetical and not reverse-alphabetical, so a
#: schema that happens to sort by some other column cannot fake a pass.
WRITE_ORDER = ["pending", "in_progress", "parked", "in_progress", "failed", "completed"]


async def _spine_engine():
    """The spine's OWN tables — `db/models.py`, not the read model."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        future=True,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed_tied_events(engine) -> None:
    """One task and six transitions that all happened at ``TIED_AT``."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as session:
        session.add(
            Conversation(id="conv-1", channel="web", created_at=TIED_AT, updated_at=TIED_AT)
        )
        session.add(
            Task(
                id="task-1",
                conversation_id="conv-1",
                request_id="req-1",
                objective="a task whose history ties",
                status="completed",
                assigned_agent="project_manager",
                privacy_level="internal",
                priority="normal",
                created_at=TIED_AT,
            )
        )
        await session.commit()

    # Committed ONE AT A TIME, so "write order" is a fact about this database
    # and not an artefact of a single multi-row INSERT's parameter order.
    previous: str | None = None
    for to_status in WRITE_ORDER:
        async with sessionmaker() as session:
            session.add(
                TaskStatusEvent(
                    task_id="task-1", from_status=previous, to_status=to_status, at=TIED_AT
                )
            )
            await session.commit()
        previous = to_status


@pytest.fixture
async def client():
    engine = await _spine_engine()
    await _seed_tied_events(engine)

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(tasks_routes.create_router())
    app.state.ops_engine = engine
    app.state.web_origin = "http://localhost:3001"

    @app.middleware("http")
    async def session_stub(request: Request, call_next):
        request.state.owner_user_id = "owner"
        return await call_next(request)

    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as c:
            yield c, engine
    finally:
        await engine.dispose()


async def test_equal_timestamp_status_events_come_back_in_write_order(client) -> None:
    """C6 §2.2 / ``TaskDetail.status_events``: "ties keep write order".

    Six transitions share one ``at``. The route's ``ORDER BY at ASC, id ASC``
    can only honour the contract if the id the spine assigns increases with
    write order — the whole point of the §5.2 disposition.
    """
    http, _engine = client

    body = (await http.get("/api/v1/tasks/task-1", headers=AUTH)).json()

    assert [e["to_status"] for e in body["status_events"]] == WRITE_ORDER
    # The timeline's other half, unchanged: `from_status` chains the transitions,
    # null only on the creation event.
    assert [e["from_status"] for e in body["status_events"]] == [None, *WRITE_ORDER[:-1]]


async def test_the_spine_assigns_ids_that_increase_with_write_order(client) -> None:
    """The property the route's tiebreak comment asserts — "a table whose id is
    a monotonic integer" — pinned at the schema, deterministically.

    A UUID id fails this on type alone, before any ordering argument: it is why
    the read model and ``db/models.py`` could disagree for a whole stream
    without a single test going red.
    """
    _http, engine = client

    async with engine.connect() as conn:
        ids = [
            row.id
            for row in (
                await conn.execute(
                    select(TaskStatusEvent.id, TaskStatusEvent.at).order_by(
                        TaskStatusEvent.id.asc()
                    )
                )
            ).fetchall()
        ]

    assert len(ids) == len(WRITE_ORDER)
    assert all(isinstance(i, int) for i in ids), ids
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
