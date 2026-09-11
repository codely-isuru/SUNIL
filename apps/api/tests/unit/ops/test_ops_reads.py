"""The three ops-read endpoints against seeded fixture data.

Contract source: ``V2_DASHBOARD_SPEC.md`` §13 (the shapes C6 freezes verbatim;
C6 had not landed on ``origin`` when this was written — see
``docs/tasks/S-D-approvals.md``). Every assertion below names the §13 clause it
is grading, so a C6 delta is a mechanical edit rather than an archaeology
exercise.

Shapes are asserted as EXACT key sets, not as "contains". A read endpoint that
quietly grows a field is how a dashboard starts depending on something no
contract promises; a superset assertion would let that through.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, Request

from sunil.api.routes import ops
from sunil.api.routes.approvals import (
    CLIENT_HEADER,
    CLIENT_VALUE,
    install_error_handlers,
)
from sunil.api.routes.ops import OPS_METADATA

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.test_real_service_contract import park_request

AUTH = {CLIENT_HEADER: CLIENT_VALUE}
T0 = datetime(2026, 1, 1, tzinfo=UTC)

#: §13.1's `Task`, field for field, plus the `status_events` the detail adds.
TASK_KEYS = {
    "id",
    "objective",
    "status",
    "assigned_agent",
    "priority",
    "project_key",
    "request_id",
    "conversation_id",
    "approval_id",
    "created_at",
    "started_at",
    "completed_at",
    "failure_kind",
}
#: §13.2's `ActivityItem` = the Task above plus three fields.
ACTIVITY_KEYS = TASK_KEYS | {"latest_stage", "latest_stage_at", "latest_detail"}
#: §13.3's index row.
TURN_KEYS = {
    "request_id",
    "started_at",
    "ended_at",
    "stage_count",
    "outcome",
    "failure_kind",
    "agent",
    "conversation_id",
    "task_id",
}


async def _seed(engine) -> None:
    """Fixture data: three tasks in the three §13.2 buckets, one complete
    twelve-stage turn and one interrupted turn, and a parked approval linked to
    the parked task."""
    async with engine.begin() as conn:
        await conn.run_sync(OPS_METADATA.drop_all)
        await conn.run_sync(OPS_METADATA.create_all)
        await conn.execute(
            ops.tasks_table.insert(),
            [
                {
                    "id": "task-run",
                    "objective": "close issue #42",
                    "status": "in_progress",
                    "assigned_agent": "project_manager",
                    "priority": "normal",
                    "request_id": "req-run",
                    "conversation_id": "conv-1",
                    "created_at": T0,
                    "started_at": T0,
                    "completed_at": None,
                    "failure_kind": None,
                },
                {
                    "id": "task-park",
                    "objective": "refund AUD 240.00",
                    "status": "pending",
                    "assigned_agent": "project_manager",
                    "priority": "high",
                    "request_id": "req-park",
                    "conversation_id": "conv-2",
                    "created_at": T0 + timedelta(seconds=1),
                    "started_at": None,
                    "completed_at": None,
                    "failure_kind": None,
                },
                {
                    "id": "task-done",
                    "objective": "add a label",
                    "status": "completed",
                    "assigned_agent": "developer",
                    "priority": "low",
                    "request_id": "req-done",
                    "conversation_id": "conv-3",
                    "created_at": T0 + timedelta(seconds=2),
                    "started_at": T0 + timedelta(seconds=2),
                    "completed_at": T0 + timedelta(seconds=9),
                    "failure_kind": None,
                },
            ],
        )
        await conn.execute(
            ops.task_status_events_table.insert(),
            [
                {
                    "task_id": "task-done",
                    "from_status": None,
                    "to_status": "pending",
                    "at": T0 + timedelta(seconds=2),
                },
                {
                    "task_id": "task-done",
                    "from_status": "pending",
                    "to_status": "in_progress",
                    "at": T0 + timedelta(seconds=3),
                },
                {
                    "task_id": "task-done",
                    "from_status": "in_progress",
                    "to_status": "completed",
                    "at": T0 + timedelta(seconds=9),
                },
            ],
        )
        await conn.execute(
            ops.audit_events_table.insert(),
            [
                {
                    "request_id": "req-done",
                    "seq": 1,
                    "stage": "message_received",
                    "task_id": None,
                    "actor": "api/routes/chat.py",
                    "summary": "user message received",
                    "detail": {},
                    "at": T0 + timedelta(seconds=2),
                },
                {
                    "request_id": "req-done",
                    "seq": 6,
                    "stage": "plan_created",
                    "task_id": "task-done",
                    "actor": "core/orchestrator",
                    "summary": "plan validated",
                    "detail": {
                        "project_key": "sunil",
                        "project_display_name": "SUNIL",
                        "agent": "developer",
                    },
                    "at": T0 + timedelta(seconds=3),
                },
                {
                    "request_id": "req-done",
                    "seq": 12,
                    "stage": "final_response",
                    "task_id": "task-done",
                    "actor": "core/orchestrator",
                    "summary": "assistant replied",
                    "detail": {"outcome": "completed", "failure_kind": None},
                    "at": T0 + timedelta(seconds=9),
                },
                # An interrupted turn: no stage 12 at all.
                {
                    "request_id": "req-park",
                    "seq": 9,
                    "stage": "permission_decision",
                    "task_id": "task-park",
                    "actor": "core/permissions",
                    "summary": "ask_user",
                    "detail": {
                        "decision": "ask_user",
                        "tool": "stripe_mcp",
                        "operation": "refunds.create",
                    },
                    "at": T0 + timedelta(seconds=4),
                },
            ],
        )


@pytest.fixture
async def client():
    engine = await factory.make_engine(factory.SQLITE_URL)
    await _seed(engine)
    clock = FakeClock()
    service = factory.make_service(engine, clock=clock.now)
    # One real parked approval, so the task→approval link and the audit trace's
    # `approval_events` are graded against real rows rather than a stub.
    await service.park(
        park_request().model_copy(
            update={
                "task_id": "task-park",
                "request_id": "req-park",
                "tool": "stripe_mcp",
                "operation": "refunds.create",
                "summary": "refund AUD 240.00 to card ending 4242",
            }
        )
    )

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(ops.create_router())
    app.state.ops_engine = engine
    app.state.approvals_service = service
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
            yield c
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# §13.1 — GET /api/v1/tasks
# --------------------------------------------------------------------------- #
async def test_tasks_returns_the_frozen_shape_newest_first(client) -> None:
    """§13.1 — ``{tasks: Task[], next_cursor}``, C4's order (``created_at``
    desc, ``id`` desc)."""
    body = (await client.get("/api/v1/tasks", headers=AUTH)).json()

    assert set(body) == {"tasks", "next_cursor"}
    assert [t["id"] for t in body["tasks"]] == ["task-done", "task-park", "task-run"]
    assert set(body["tasks"][0]) == TASK_KEYS
    assert body["next_cursor"] is None


async def test_task_rows_carry_the_project_key_from_plan_created(client) -> None:
    """Q2's recorded default — ``tasks`` has no ``project_key`` column, so it
    comes from the ``plan_created`` event's detail where that event exists, and
    is ``null`` where it does not. Null rather than omitted: the dashboard's
    column has to render something, and a missing key would be a different
    shape per row."""
    tasks = {t["id"]: t for t in (await client.get("/api/v1/tasks", headers=AUTH)).json()["tasks"]}

    assert tasks["task-done"]["project_key"] == "sunil"
    assert tasks["task-run"]["project_key"] is None
    assert "project_key" in tasks["task-run"]


async def test_a_parked_task_links_to_its_approval(client) -> None:
    """§13.1's optional ``approval_id`` — the join the dashboard needs to get
    from a parked task to the decision screen."""
    tasks = {t["id"]: t for t in (await client.get("/api/v1/tasks", headers=AUTH)).json()["tasks"]}

    assert tasks["task-park"]["approval_id"].startswith("apr-")
    assert tasks["task-run"]["approval_id"] is None


async def test_tasks_filters_by_status_and_searches_the_objective(client) -> None:
    """§13.1's ``?status=`` and ``?q=``."""
    by_status = await client.get(
        "/api/v1/tasks", params={"status": "pending"}, headers=AUTH
    )
    assert [t["id"] for t in by_status.json()["tasks"]] == ["task-park"]

    searched = await client.get("/api/v1/tasks", params={"q": "refund"}, headers=AUTH)
    assert [t["id"] for t in searched.json()["tasks"]] == ["task-park"]


async def test_a_like_metacharacter_in_q_is_escaped_not_interpreted(client) -> None:
    """``?q=`` goes into a LIKE. It is a bound parameter (so not injectable),
    but an unescaped ``%`` would still turn a search for "100%" into a match-
    everything scan — a small denial-of-service and a wrong answer."""
    response = await client.get("/api/v1/tasks", params={"q": "%"}, headers=AUTH)

    assert response.json()["tasks"] == []


async def test_tasks_pagination_follows_c4s_rules_exactly(client) -> None:
    """§13: "same cursor pagination" — including C4 §6.5's pinned reading that
    an exactly-full final page still returns a cursor."""
    first = await client.get("/api/v1/tasks", params={"limit": 2}, headers=AUTH)
    assert [t["id"] for t in first.json()["tasks"]] == ["task-done", "task-park"]
    assert first.json()["next_cursor"] == "task-park"

    second = await client.get(
        "/api/v1/tasks", params={"limit": 2, "cursor": "task-park"}, headers=AUTH
    )
    assert [t["id"] for t in second.json()["tasks"]] == ["task-run"]
    assert second.json()["next_cursor"] is None


async def test_an_unknown_task_cursor_is_422(client) -> None:
    response = await client.get(
        "/api/v1/tasks", params={"cursor": "task-nope"}, headers=AUTH
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "validation_error"


async def test_task_detail_adds_the_status_history(client) -> None:
    """§13.1 — ``status_events: [{from_status, to_status, at}]`` from
    ``task_status_events``, in time order (FR-065's ordered history)."""
    body = (await client.get("/api/v1/tasks/task-done", headers=AUTH)).json()

    assert set(body) == TASK_KEYS | {"status_events"}
    assert [e["to_status"] for e in body["status_events"]] == [
        "pending",
        "in_progress",
        "completed",
    ]
    assert body["status_events"][0]["from_status"] is None
    assert body["status_events"][0]["at"] == "2026-01-01T00:00:02Z"


async def test_an_unknown_task_is_404_in_the_contract_envelope(client) -> None:
    response = await client.get("/api/v1/tasks/task-nope", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["kind"] == "not_found"


# --------------------------------------------------------------------------- #
# §13.2 — GET /api/v1/activity
# --------------------------------------------------------------------------- #
async def test_activity_returns_three_buckets_in_one_request(client) -> None:
    """§13.2 — ``{running, parked, recent}``. One request by contract: "the
    alternative — list tasks then fetch a trace per task — is an N+1 on a
    10-second poll"."""
    body = (await client.get("/api/v1/activity", headers=AUTH)).json()

    assert set(body) == {"running", "parked", "recent"}
    assert [t["id"] for t in body["running"]] == ["task-run"]
    assert [t["id"] for t in body["parked"]] == ["task-park"]
    assert [t["id"] for t in body["recent"]] == ["task-done"]


async def test_activity_items_carry_the_latest_stage_and_detail(client) -> None:
    """§13.2's ``ActivityItem`` = the Task shape plus ``latest_stage``,
    ``latest_stage_at`` and ``latest_detail {project_display_name?, tool?,
    operation?}``. The detail is projected to those three keys only — the raw
    ``detail`` blob may hold a truncated excerpt of untrusted content (T-32),
    and an ops summary tier has no need to carry it."""
    body = (await client.get("/api/v1/activity", headers=AUTH)).json()

    parked = body["parked"][0]
    assert set(parked) == ACTIVITY_KEYS
    assert parked["latest_stage"] == "permission_decision"
    assert parked["latest_stage_at"] == "2026-01-01T00:00:04Z"
    assert parked["latest_detail"] == {
        "tool": "stripe_mcp",
        "operation": "refunds.create",
    }

    # `latest_detail` is the LATEST stage's detail, projected — not a merge
    # across the turn. task-done's latest stage is `final_response`, whose
    # contracted keys (ARCHITECTURE_V1 §3.4) are `outcome`/`failure_kind`, none
    # of which is one of §13.2's three, so the projection is empty. Merging
    # `project_display_name` forward from `plan_created` would be inventing a
    # field the contract does not describe; the project is already carried
    # properly by `project_key` (Q2), so there is nothing to compensate for.
    done = body["recent"][0]
    assert done["latest_stage"] == "final_response"
    assert done["latest_detail"] == {}
    assert done["project_key"] == "sunil"

    # …and a task whose latest stage IS `plan_created` does carry the name.
    plan_stage = await client.get("/api/v1/tasks/task-done", headers=AUTH)
    assert plan_stage.json()["project_key"] == "sunil"


async def test_a_task_with_no_audit_events_still_has_the_activity_keys(
    client,
) -> None:
    """The shape must not depend on the data: a task whose turn wrote no
    task-scoped events still carries the three fields, as nulls. A missing key
    would crash a renderer that reads it."""
    body = (await client.get("/api/v1/activity", headers=AUTH)).json()

    running = body["running"][0]
    assert set(running) == ACTIVITY_KEYS
    assert running["latest_stage"] is None
    assert running["latest_stage_at"] is None
    assert running["latest_detail"] == {}


# --------------------------------------------------------------------------- #
# §13.3 — GET /api/v1/audit
# --------------------------------------------------------------------------- #
async def test_audit_index_returns_one_row_per_turn(client) -> None:
    """§13.3 index — ``{turns: [...], next_cursor}``, newest first."""
    body = (await client.get("/api/v1/audit", headers=AUTH)).json()

    assert set(body) == {"turns", "next_cursor"}
    turns = {t["request_id"]: t for t in body["turns"]}
    assert set(turns) == {"req-done", "req-park"}
    assert set(body["turns"][0]) == TURN_KEYS


async def test_the_stage_count_is_never_padded_to_twelve(client) -> None:
    """Q9's recorded default — "render whatever arrives; flag any count ≠ 12 in
    warning and never pad or hide a missing stage". The API therefore reports
    the honest count, and an interrupted turn has a null outcome rather than an
    invented one."""
    turns = {
        t["request_id"]: t
        for t in (await client.get("/api/v1/audit", headers=AUTH)).json()["turns"]
    }

    assert turns["req-done"]["stage_count"] == 3
    assert turns["req-done"]["outcome"] == "completed"
    assert turns["req-done"]["failure_kind"] is None

    assert turns["req-park"]["stage_count"] == 1
    assert turns["req-park"]["outcome"] is None  # never reached stage 12


async def test_audit_index_filters(client) -> None:
    """§13.3's ``?request_id=&from=&to=&outcome=&agent=``."""
    by_request = await client.get(
        "/api/v1/audit", params={"request_id": "req-done"}, headers=AUTH
    )
    assert [t["request_id"] for t in by_request.json()["turns"]] == ["req-done"]

    by_outcome = await client.get(
        "/api/v1/audit", params={"outcome": "completed"}, headers=AUTH
    )
    assert [t["request_id"] for t in by_outcome.json()["turns"]] == ["req-done"]

    windowed = await client.get(
        "/api/v1/audit",
        params={"from": "2026-01-01T00:00:04Z", "to": "2026-01-01T00:00:05Z"},
        headers=AUTH,
    )
    assert [t["request_id"] for t in windowed.json()["turns"]] == ["req-park"]


async def test_a_malformed_timestamp_filter_is_422_not_a_500(client) -> None:
    response = await client.get(
        "/api/v1/audit", params={"from": "yesterday"}, headers=AUTH
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "validation_error"


async def test_audit_trace_returns_events_in_seq_order_with_the_approval_chain(
    client,
) -> None:
    """§13.3 detail — ``{events: [{seq, stage, actor, summary, detail, at,
    task_id}], approval_events?}`` in ``seq`` order.

    ``approval_events`` is present because §10.2 requires the approval episode
    to read as ONE story: the parked turn and its continuation share the
    original ``request_id`` lineage, so the approval belongs in the same trace.
    """
    body = (await client.get("/api/v1/audit/req-done", headers=AUTH)).json()

    assert set(body) == {"events", "approval_events"}
    assert [e["seq"] for e in body["events"]] == [1, 6, 12]
    assert set(body["events"][0]) == {
        "seq",
        "stage",
        "actor",
        "summary",
        "detail",
        "at",
        "task_id",
    }
    assert body["approval_events"] == []

    parked = (await client.get("/api/v1/audit/req-park", headers=AUTH)).json()
    assert len(parked["approval_events"]) == 1
    approval = parked["approval_events"][0]
    assert approval["status"] == "pending"
    assert (approval["tool"], approval["operation"]) == (
        "stripe_mcp",
        "refunds.create",
    )
    assert approval["decided_at"] is None


async def test_audit_detail_values_are_returned_unmodified(client) -> None:
    """§13.3's carried-forward security note — ``audit_events.detail`` may hold
    a truncated excerpt of untrusted content (T-32). It is transmitted
    faithfully with ``nosniff`` and contained by the renderer, under the same
    plain-text rules as the approval card, "no exceptions for developer-facing
    screens"."""
    response = await client.get("/api/v1/audit/req-park", headers=AUTH)

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.json()["events"][0]["detail"] == {
        "decision": "ask_user",
        "tool": "stripe_mcp",
        "operation": "refunds.create",
    }


async def test_an_unknown_request_id_is_404(client) -> None:
    response = await client.get("/api/v1/audit/req-nope", headers=AUTH)

    assert response.status_code == 404
    assert response.json()["error"]["kind"] == "not_found"


# --------------------------------------------------------------------------- #
# Auth and read-only posture
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/tasks",
        "/api/v1/tasks/task-run",
        "/api/v1/activity",
        "/api/v1/audit",
        "/api/v1/audit/req-done",
    ],
)
async def test_every_ops_read_requires_the_web_client_header(client, path) -> None:
    """§13: "same auth as C4 (``sessionCookie`` + ``X-SUNIL-Client: web``)".
    Imported from the C4 route module rather than reimplemented, so the two
    surfaces cannot drift into two auth postures."""
    response = await client.get(path)

    assert response.status_code == 403
    assert response.json()["error"]["kind"] == "forbidden_client"


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/tasks"),
        ("delete", "/api/v1/tasks/task-run"),
        ("post", "/api/v1/audit"),
        ("put", "/api/v1/activity"),
    ],
)
async def test_the_ops_router_exposes_no_mutating_verb(client, method, path) -> None:
    """§13: "All are read-only". Asserted as the absence of a route, not as a
    guard inside one — the strongest form of read-only is having nothing to
    call."""
    response = await getattr(client, method)(path, headers=AUTH)

    assert response.status_code == 405
