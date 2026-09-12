"""C6 v1.0.0 — the three ops-read surfaces, graded against the frozen contract.

Every test names the C6 clause it grades. C6 §6 lists ten contract tests for the
QA fake; these are the same ten behaviours asserted against Stream D's REAL
routes over a real database, which is the evidence Stream D owes (the fake and
`tests/contracts/test_c6_ops_reads.py` are QA's deliverable, not this branch's).

Shapes are asserted as EXACT key sets. A read endpoint that quietly grows a
field is how a dashboard starts depending on something no contract promises.
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request

from sunil.api.routes import activity as activity_routes
from sunil.api.routes import audit as audit_routes
from sunil.api.routes import tasks as tasks_routes
from sunil.api.routes.approvals import (
    CLIENT_HEADER,
    CLIENT_VALUE,
    install_error_handlers,
)

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.test_real_service_contract import park_request
from tests.unit.ops import fixture
from tests.unit.ops.fixture import UNTRUSTED_OBJECTIVE

#: ADR-008 Amendment 1 (wave-1 ruling R3): the CSRF pair is two controls, and an
#: absent `Origin` is now a mismatch on every route that applies it — so an
#: authorised request in this suite sends the full browser sentence.
AUTH = {CLIENT_HEADER: CLIENT_VALUE, "Origin": "http://localhost:3001"}

#: C6 Task — every key always present, absence expressed as null.
TASK_KEYS = {
    "id", "objective", "status", "assigned_agent", "priority", "project_key",
    "request_id", "conversation_id", "approval_id", "created_at", "started_at",
    "completed_at", "failure_kind",
}
ACTIVITY_KEYS = TASK_KEYS | {"latest_stage", "latest_stage_at", "latest_detail"}
TURN_KEYS = {
    "request_id", "started_at", "ended_at", "stage_count", "outcome",
    "failure_kind", "agent", "conversation_id", "task_id",
}
EVENT_KEYS = {"seq", "stage", "actor", "summary", "detail", "at", "task_id"}


@pytest.fixture
async def client():
    engine = await factory.make_engine(factory.SQLITE_URL)
    await fixture.seed(engine)
    clock = FakeClock()
    service = factory.make_service(engine, clock=clock.now)
    # A real parked approval so `task-5`'s `approval_id` link is graded against
    # a real row rather than a stub.
    await service.park(
        park_request().model_copy(
            update={
                "task_id": "task-5",
                "request_id": "req-parked",
                "tool": "stripe_mcp",
                "operation": "refunds.create",
                "summary": UNTRUSTED_OBJECTIVE,
            }
        )
    )

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(tasks_routes.create_router())
    app.include_router(activity_routes.create_router())
    app.include_router(audit_routes.create_router())
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


async def _get(client, path, **params):
    r = await client.get(path, headers=AUTH, params=params)
    return r


# --------------------------------------------------------------------------- #
# C6 test 1 — the order law
# --------------------------------------------------------------------------- #
async def test_tasks_are_ordered_created_at_desc_then_id_desc(client) -> None:
    """C6 §2.1.1. The fixture's ``task-9``/``task-10`` share a ``created_at``,
    so only the id breaks the tie — and id comparison is PLAIN STRING, so
    ``task-9`` sorts ABOVE ``task-10`` (the F8 reading)."""
    body = (await _get(client, "/api/v1/tasks", limit=200)).json()
    ids = [t["id"] for t in body["tasks"]]
    assert set(body) == {"tasks", "next_cursor"}
    assert set(body["tasks"][0]) == TASK_KEYS
    assert ids[:3] == ["task-33", "task-32", "task-31"]
    tie = ids[ids.index("task-9")], ids[ids.index("task-9") + 1]
    assert tie == ("task-9", "task-10")


async def test_order_oldest_reverses_both_sort_keys(client) -> None:
    """C6 §2.1.6 — ``oldest`` is ``created_at asc, id asc``, reversing the tie
    too. Reversing only the returned PAGE would put the newest rows on page one
    and is the bug this test exists to catch."""
    body = (await _get(client, "/api/v1/tasks", order="oldest", limit=10)).json()
    ids = [t["id"] for t in body["tasks"]]
    assert ids == [f"task-{n}" for n in range(1, 9)] + ["task-10", "task-9"]


# --------------------------------------------------------------------------- #
# C6 test 2 — the cursor law
# --------------------------------------------------------------------------- #
async def test_an_exactly_full_final_page_still_returns_a_cursor(client) -> None:
    """C6 §2.1.3 — ``next_cursor`` is null ONLY on a short page. The two parked
    tasks at ``limit=2`` are an exactly-full FINAL page: the cursor is non-null
    and the client learns it is done from the following EMPTY page."""
    first = (await _get(client, "/api/v1/tasks", status="parked", limit=2)).json()
    assert [t["id"] for t in first["tasks"]] == ["task-8", "task-5"]
    assert first["next_cursor"] == "task-5"
    second = (
        await _get(
            client, "/api/v1/tasks", status="parked", limit=2,
            cursor=first["next_cursor"],
        )
    ).json()
    assert second == {"tasks": [], "next_cursor": None}


async def test_a_short_page_returns_a_null_cursor(client) -> None:
    """C6 §2.1.3, the other half."""
    body = (await _get(client, "/api/v1/tasks", status="parked", limit=50)).json()
    assert len(body["tasks"]) == 2
    assert body["next_cursor"] is None


async def test_an_unknown_task_cursor_is_422(client) -> None:
    """C6 §2.1.4 — never a silent page one."""
    r = await _get(client, "/api/v1/tasks", cursor="task-does-not-exist")
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "validation_error"


@pytest.mark.parametrize("limit", [0, 201])
async def test_limits_outside_1_200_are_422(client, limit) -> None:
    """C6 §2.1.5."""
    r = await _get(client, "/api/v1/tasks", limit=limit)
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# C6 test 3 — filters, and filters BEFORE pagination
# --------------------------------------------------------------------------- #
async def test_the_project_key_filter_is_applied_before_pagination(client) -> None:
    """C6 §2.1.2 — "filters apply BEFORE ordering and pagination". The three
    ``sunil`` tasks are old, so a filter applied to an already-paginated page
    would return an EMPTY first page here; a page walk over the filtered set
    returns them two-then-one."""
    first = (
        await _get(client, "/api/v1/tasks", project_key="sunil", limit=2)
    ).json()
    assert [t["id"] for t in first["tasks"]] == ["task-5", "task-4"]
    assert first["next_cursor"] == "task-4"
    second = (
        await _get(
            client, "/api/v1/tasks", project_key="sunil", limit=2,
            cursor=first["next_cursor"],
        )
    ).json()
    assert [t["id"] for t in second["tasks"]] == ["task-1"]
    assert second["next_cursor"] is None


async def test_project_key_is_a_column_not_a_derivation(client) -> None:
    """C6 §3 (Q2 ruling) — ``tasks.project_key``, written once at creation.
    ``task-4`` has no ``plan_created`` audit row at all, so a value derived from
    audit detail would be null here."""
    body = (await _get(client, "/api/v1/tasks", project_key="sunil")).json()
    assert {t["id"] for t in body["tasks"]} == {"task-1", "task-4", "task-5"}
    assert all(t["project_key"] == "sunil" for t in body["tasks"])


async def test_q_is_a_case_insensitive_substring_over_the_objective(client) -> None:
    """C6 §2.2 — case-INSENSITIVE. ``task-1``'s objective is "Refund AUD…"."""
    body = (await _get(client, "/api/v1/tasks", q="refund")).json()
    assert [t["id"] for t in body["tasks"]] == ["task-1"]


async def test_a_like_metacharacter_in_q_is_escaped_not_interpreted(client) -> None:
    """``q`` reaches a LIKE: ``%`` must match a literal percent sign, not
    everything."""
    body = (await _get(client, "/api/v1/tasks", q="%")).json()
    assert body["tasks"] == []


async def test_filters_compose_with_and(client) -> None:
    """C6 §2.2 — "filters compose with AND"."""
    body = (
        await _get(client, "/api/v1/tasks", status="parked", project_key="sunil")
    ).json()
    assert [t["id"] for t in body["tasks"]] == ["task-5"]


async def test_a_status_outside_the_enum_is_422(client) -> None:
    """C6 §2.2 — ``status`` (enum, 422 outside it)."""
    r = await _get(client, "/api/v1/tasks", status="snoozed")
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "validation_error"


# --------------------------------------------------------------------------- #
# C6 test 4 — task detail
# --------------------------------------------------------------------------- #
async def test_task_detail_adds_the_status_history_ascending(client) -> None:
    """C6 §2.2 — ``status_events`` ascending ``at``, ``from_status`` null on the
    creation event."""
    body = (await client.get("/api/v1/tasks/task-3", headers=AUTH)).json()
    assert set(body) == TASK_KEYS | {"status_events"}
    assert [e["to_status"] for e in body["status_events"]] == [
        "pending", "in_progress", "completed",
    ]
    assert body["status_events"][0]["from_status"] is None
    assert set(body["status_events"][0]) == {"from_status", "to_status", "at"}


async def test_a_parked_task_links_to_its_approval(client) -> None:
    """C6 §2.2 — ``approval_id`` is the C4 linkage, the only C4 field C6 carries."""
    body = (await client.get("/api/v1/tasks/task-5", headers=AUTH)).json()
    assert body["approval_id"] is not None
    assert (await client.get("/api/v1/tasks/task-3", headers=AUTH)).json()[
        "approval_id"
    ] is None


async def test_an_unknown_task_is_404_in_the_contract_envelope(client) -> None:
    r = await client.get("/api/v1/tasks/task-nope", headers=AUTH)
    assert r.status_code == 404
    assert r.json()["error"]["kind"] == "not_found"


# --------------------------------------------------------------------------- #
# C6 test 5 — the activity partition
# --------------------------------------------------------------------------- #
async def test_activity_partitions_by_status_exactly(client) -> None:
    """C6 §2.3 — ``running`` = pending + in_progress, ``parked`` = parked,
    ``recent`` = completed + failed. One request, no parameters."""
    body = (await client.get("/api/v1/activity", headers=AUTH)).json()
    assert set(body) == {"running", "parked", "recent"}
    assert [t["id"] for t in body["running"]] == [
        "task-12", "task-9", "task-10", "task-2", "task-1",
    ]
    assert [t["id"] for t in body["parked"]] == ["task-8", "task-5"]
    assert set(body["running"][0]) == ACTIVITY_KEYS


async def test_recent_is_capped_at_the_twenty_newest(client) -> None:
    """C6 §2.3 — capped at the 20 most recent, AFTER ordering. The fixture has
    26 terminal tasks, so the 21st (``task-13``) must be absent."""
    body = (await client.get("/api/v1/activity", headers=AUTH)).json()
    ids = [t["id"] for t in body["recent"]]
    assert len(ids) == 20
    assert ids[0] == "task-33"
    assert ids[-1] == "task-14"
    assert "task-13" not in ids


async def test_activity_folds_in_the_highest_seq_audit_row(client) -> None:
    """C6 §2.3 — ``latest_stage``/``latest_stage_at`` come from the HIGHEST-SEQ
    row for the task's ``request_id`` (not the task_id, and not the newest
    ``at``)."""
    body = (await client.get("/api/v1/activity", headers=AUTH)).json()
    live = next(t for t in body["running"] if t["id"] == "task-2")
    assert live["latest_stage"] == "plan_created"
    assert live["latest_stage_at"] == "2026-01-01T00:05:05Z"


async def test_latest_detail_projects_only_the_three_contracted_keys(client) -> None:
    """C6 §2.3 — "other detail keys MUST NOT pass through the projection". The
    fixture's highest-seq ``req-live`` row carries a ``secret_excerpt``."""
    body = (await client.get("/api/v1/activity", headers=AUTH)).json()
    live = next(t for t in body["running"] if t["id"] == "task-2")
    assert live["latest_detail"] == {"project_display_name": "SUNIL"}


async def test_a_task_with_no_audit_rows_still_carries_the_keys(client) -> None:
    """C6 §2.3 — both ``latest_*`` fields null when no audit row exists."""
    body = (await client.get("/api/v1/activity", headers=AUTH)).json()
    bare = next(t for t in body["running"] if t["id"] == "task-12")
    assert set(bare) == ACTIVITY_KEYS
    assert bare["latest_stage"] is None
    assert bare["latest_stage_at"] is None
    assert bare["latest_detail"] == {}


# --------------------------------------------------------------------------- #
# C6 test 6 — audit derivations
# --------------------------------------------------------------------------- #
async def test_audit_index_returns_one_row_per_turn_newest_first(client) -> None:
    """C6 §2.4 — grouped by ``request_id``, ordered ``started_at desc,
    request_id desc``."""
    body = (await client.get("/api/v1/audit", headers=AUTH)).json()
    assert set(body) == {"turns", "next_cursor"}
    assert [t["request_id"] for t in body["turns"]] == [
        "req-live", "req-parked", "req-full",
    ]
    assert set(body["turns"][0]) == TURN_KEYS


async def test_an_in_flight_turn_has_a_null_ended_at_and_outcome(client) -> None:
    """C6 §2.4 — ``ended_at`` is the ``final_response`` row's ``at``, NULL while
    in flight; it is not "the last row seen"."""
    turns = {
        t["request_id"]: t
        for t in (await client.get("/api/v1/audit", headers=AUTH)).json()["turns"]
    }
    live = turns["req-live"]
    assert live["ended_at"] is None
    assert live["outcome"] is None
    assert live["failure_kind"] is None
    assert live["started_at"] == "2026-01-01T00:05:01Z"
    assert live["stage_count"] == 5


async def test_stage_count_counts_spine_rows_only(client) -> None:
    """C6 §2.4 — approval-episode rows are NOT counted, so the view's "n of 12"
    reading stays honest. ``req-parked`` has 12 rows, two of which are lifecycle
    kinds."""
    turns = {
        t["request_id"]: t
        for t in (await client.get("/api/v1/audit", headers=AUTH)).json()["turns"]
    }
    assert turns["req-full"]["stage_count"] == 12
    assert turns["req-parked"]["stage_count"] == 10


async def test_agent_outcome_and_conversation_are_derived_from_contracted_keys(
    client,
) -> None:
    """C6 §2.4 — ``agent`` from ``plan_created.detail.agent``, ``outcome`` from
    ``final_response.detail``, ``conversation_id``/``task_id`` through the
    turn's task."""
    turns = {
        t["request_id"]: t
        for t in (await client.get("/api/v1/audit", headers=AUTH)).json()["turns"]
    }
    full = turns["req-full"]
    assert full["agent"] == "project_manager"
    assert full["outcome"] == "ok"
    assert full["ended_at"] == "2026-01-01T00:01:52Z"
    assert full["conversation_id"] == "conv-1"
    assert full["task_id"] == "task-1"
    assert turns["req-live"]["agent"] == "developer"


# --------------------------------------------------------------------------- #
# C6 test 7 — audit filters + pagination
# --------------------------------------------------------------------------- #
async def test_request_id_filter_returns_zero_or_one_turn(client) -> None:
    body = (await _get(client, "/api/v1/audit", request_id="req-parked")).json()
    assert [t["request_id"] for t in body["turns"]] == ["req-parked"]
    assert (await _get(client, "/api/v1/audit", request_id="nope")).json()[
        "turns"
    ] == []


async def test_from_and_to_are_half_open_on_started_at(client) -> None:
    """C6 §2.4 — ``from <= started_at < to``: the row exactly at ``from`` is IN,
    the row exactly at ``to`` is OUT, and the window is on the TURN's
    ``started_at``, not on individual rows' ``at``."""
    body = (
        await _get(
            client, "/api/v1/audit",
            **{"from": "2026-01-01T00:03:21Z", "to": "2026-01-01T00:05:01Z"},
        )
    ).json()
    assert [t["request_id"] for t in body["turns"]] == ["req-parked"]


async def test_a_malformed_timestamp_filter_is_422_not_a_500(client) -> None:
    r = await _get(client, "/api/v1/audit", **{"from": "yesterday"})
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "validation_error"


async def test_the_audit_cursor_law_matches_the_task_cursor_law(client) -> None:
    """C6 §2.1 applied to ``request_id desc`` — including the exactly-full final
    page and the 422 on an unknown cursor."""
    first = (await _get(client, "/api/v1/audit", limit=3)).json()
    assert len(first["turns"]) == 3
    assert first["next_cursor"] == "req-full"
    assert (
        await _get(client, "/api/v1/audit", limit=3, cursor="req-full")
    ).json() == {"turns": [], "next_cursor": None}
    r = await _get(client, "/api/v1/audit", cursor="req-nope")
    assert r.status_code == 422


async def test_the_outcome_and_agent_filters_run_on_the_derived_values(
    client,
) -> None:
    """C6 §2.4 — ``agent`` is the derived ``plan_created.detail.agent``, not
    ``audit_events.actor`` (every fixture row's actor is "core")."""
    assert [
        t["request_id"]
        for t in (await _get(client, "/api/v1/audit", agent="developer")).json()[
            "turns"
        ]
    ] == ["req-live", "req-parked"]
    assert [
        t["request_id"]
        for t in (await _get(client, "/api/v1/audit", outcome="ok")).json()["turns"]
    ] == ["req-parked", "req-full"]


# --------------------------------------------------------------------------- #
# C6 test 8 — the detail partition
# --------------------------------------------------------------------------- #
async def test_the_turn_detail_partitions_the_approval_episode(client) -> None:
    """C6 §2.4 — ``approval_events`` = lifecycle kinds UNION rows whose detail
    carries ``resumed_from_approval_id``; ``events`` = every other row; both
    ascending ``seq``."""
    body = (await client.get("/api/v1/audit/req-parked", headers=AUTH)).json()
    assert set(body) == {"events", "approval_events"}
    assert [e["seq"] for e in body["events"]] == list(range(1, 9))
    assert [e["seq"] for e in body["approval_events"]] == [9, 10, 11, 12]
    # The continuation rows land there by DETAIL, not by stage name.
    assert [e["stage"] for e in body["approval_events"][2:]] == [
        "tool_result", "final_response",
    ]
    assert set(body["events"][0]) == EVENT_KEYS


async def test_a_turn_with_no_episode_has_a_null_approval_events(client) -> None:
    """C6 §2.4 — null, not an empty array: "no episode" and "an empty episode"
    are different facts and the UI renders only one of them."""
    body = (await client.get("/api/v1/audit/req-full", headers=AUTH)).json()
    assert body["approval_events"] is None
    assert len(body["events"]) == 12


async def test_an_unknown_request_id_is_404(client) -> None:
    r = await client.get("/api/v1/audit/req-nope", headers=AUTH)
    assert r.status_code == 404
    assert r.json()["error"]["kind"] == "not_found"


# --------------------------------------------------------------------------- #
# C6 test 10 — byte fidelity
# --------------------------------------------------------------------------- #
async def test_untrusted_values_come_back_byte_identical(client) -> None:
    """C6 §4 — "the server MUST NOT sanitise, escape or strip these values".
    The same string is probed through list, detail, activity and the audit
    summary, because a sanitiser usually gets added in exactly one of them."""
    listed = (await _get(client, "/api/v1/tasks", status="parked")).json()["tasks"]
    assert next(t for t in listed if t["id"] == "task-5")["objective"] == (
        UNTRUSTED_OBJECTIVE
    )
    detail = (await client.get("/api/v1/tasks/task-5", headers=AUTH)).json()
    assert detail["objective"] == UNTRUSTED_OBJECTIVE
    act = (await client.get("/api/v1/activity", headers=AUTH)).json()
    assert next(t for t in act["parked"] if t["id"] == "task-5")["objective"] == (
        UNTRUSTED_OBJECTIVE
    )
    turn = (await client.get("/api/v1/audit/req-parked", headers=AUTH)).json()
    requested = next(
        e for e in turn["approval_events"] if e["stage"] == "approval_requested"
    )
    assert requested["summary"] == UNTRUSTED_OBJECTIVE
    assert requested["detail"] == {"approval_id": "apr-1"}


# --------------------------------------------------------------------------- #
# C6 test 9 (the half this branch can prove) — auth posture and read-only-ness
# --------------------------------------------------------------------------- #
C6_PATHS = [
    "/api/v1/tasks",
    "/api/v1/tasks/task-1",
    "/api/v1/activity",
    "/api/v1/audit",
    "/api/v1/audit/req-full",
]


@pytest.mark.parametrize("path", C6_PATHS)
async def test_every_c6_read_requires_the_web_client_header(client, path) -> None:
    """C6 §1 — the exact C4 lane. Without ``X-SUNIL-Client: web`` it is 403."""
    r = await client.get(path)
    assert r.status_code == 403
    assert r.json()["error"]["kind"] == "forbidden_client"


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
@pytest.mark.parametrize("path", ["/api/v1/tasks", "/api/v1/activity", "/api/v1/audit"])
async def test_no_mutating_verb_exists_on_the_c6_surface(client, method, path) -> None:
    """C6 §1 — "a POST/PUT/DELETE on these paths is 405 from the framework, not
    a handler"."""
    r = await getattr(client, method)(path, headers=AUTH)
    assert r.status_code == 405


def test_the_c6_operation_ids_are_the_contracts(client) -> None:
    """C6 §1 names five operations; ``getAuditTurn`` in particular (an earlier
    draft called it ``getAuditTrace``). The ids are the client-generator's
    contract, so they are graded."""
    ids = set()
    for module in (tasks_routes, activity_routes, audit_routes):
        for route in module.create_router().routes:
            ids.add(route.operation_id)
    assert ids == {
        "listTasks", "getTask", "getActivity", "listAuditTurns", "getAuditTurn",
    }
