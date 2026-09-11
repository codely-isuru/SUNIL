"""The three ops-read endpoints the dashboard cannot start without — tasks,
activity and audit.

**Contract status.** ``V2_DASHBOARD_SPEC.md`` §13 proposes these three as
read-only, owner-session-only surfaces with C4's auth, C4's error envelope and
C4's cursor pagination; Q1's recorded default is to build to §13's shapes. The
Solution Architect is freezing them as **C6** (``task/S0-ops-contracts``). That
branch had not landed when this module was written, so every shape here is
§13's **verbatim**, which C6 freezes verbatim in turn. If C6 renames or adds a
field, the change lands here and in ``tests/unit/ops/`` and nowhere else — the
route bodies below are thin projections over queries, deliberately, so that a
contract delta is an edit to a field map rather than a redesign.

**Read-only, and structurally so.** Every statement in this module is a
``SELECT``. There is no INSERT, UPDATE or DELETE, and the routes take a
``connect()`` (not ``begin()``) connection, so an accidental write would have no
transaction to commit into. That is the property §13 asks for ("All are
read-only").

**Whose tables these are.** ``tasks``, ``task_status_events`` and
``audit_events`` belong to the spine lane's base schema; Stream D only reads
them. So they are declared here as a **read model** on a private ``MetaData``,
transcribed from ``ARCHITECTURE_V1.md`` §33's schema — the column lists are the
spine's, not a proposal. At integration the spine's real table objects supersede
these declarations (same names, same columns); until then this module compiles
and is testable in a worktree that has no ``db/models.py``. The read model
declares only the columns §13's shapes actually need, because a read model that
mirrors every column invites somebody to read one that is not in a contract.

**Q2 (no ``tasks.project_key`` column).** §13's ``Task`` carries
``project_key``, but ARCHITECTURE_V1 §33's ``tasks`` has no such column — the
project lives in ``audit_events.detail`` for the ``plan_created`` stage. Q2's
recorded default is "show the project only where ``plan_created.detail`` is
available", so that is what happens: ``project_key`` is sourced from the
``plan_created`` event for the task's ``request_id``, in **one batched query per
page** rather than a per-row lookup, and is ``null`` when the event is absent.
The ``?project_key=`` filter is therefore honoured only against what that source
can answer, and is documented as such rather than silently ignored.

**The untrusted-text rule reaches further here than in C4.** §13.3's carried-
forward security note: ``audit_events.detail`` may contain a truncated excerpt
of untrusted content (ARCHITECTURE_V1 §3.4, T-32). It is returned as JSON data,
unmodified, with ``nosniff`` — the same posture as C4's ``summary``, and the
audit browser renders it under the same plain-text rules with, in §13.3's
words, "no exceptions for developer-facing screens".
"""

from __future__ import annotations

from datetime import UTC as _UTC
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request, Response
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    JSON,
    MetaData,
    String,
    Table,
    select,
    tuple_,
)

from sunil.api.routes.approvals import (
    NOSNIFF,
    ApiError,
    OwnerSession,
    WebClient,
)
from sunil.core.approvals.service import to_iso
from sunil.core.approvals.table import approvals_table

#: Stream D's private read model over the spine's tables — see the docstring.
OPS_METADATA = MetaData()

#: ARCHITECTURE_V1 §33 `tasks`, plus §13.1's shape. `project_key` is absent on
#: purpose (Q2): it is not a column.
tasks_table = Table(
    "tasks",
    OPS_METADATA,
    Column("id", String(64), primary_key=True),
    Column("objective", String, nullable=False),
    Column("status", String(32), nullable=False),
    Column("assigned_agent", String(128), nullable=True),
    Column("priority", String(32), nullable=True),
    Column("request_id", String(64), nullable=False),
    Column("conversation_id", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("failure_kind", String(64), nullable=True),
)

#: ARCHITECTURE_V1 §33 `task_status_events` — §13.1's `status_events`.
task_status_events_table = Table(
    "task_status_events",
    OPS_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", String(64), nullable=False),
    Column("from_status", String(32), nullable=True),
    Column("to_status", String(32), nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
)

#: ARCHITECTURE_V1 §33 `audit_events` — the table ET-6 is graded against.
audit_events_table = Table(
    "audit_events",
    OPS_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("request_id", String(64), nullable=False),
    Column("seq", Integer, nullable=False),
    Column("stage", String(64), nullable=False),
    Column("task_id", String(64), nullable=True),
    Column("actor", String(128), nullable=False),
    Column("summary", String, nullable=False),
    Column("detail", JSON, nullable=True),
    Column("at", DateTime(timezone=True), nullable=False),
)

#: The twelve NFR-020 stages in order (ARCHITECTURE_V1 §3.4 / ADR-023). Used to
#: pick a turn's outcome event without assuming stage 12 is the highest `seq`.
FINAL_STAGE = "final_response"
PLAN_STAGE = "plan_created"

#: §13.2's three activity buckets, keyed to `tasks.status`.
RUNNING_STATUSES = ("in_progress",)
PARKED_STATUSES = ("pending",)

T = tasks_table
E = audit_events_table
S = task_status_events_table
A = approvals_table


def _iso(value: Any) -> str | None:
    """Render a timestamp column in the contracts' ``…Z`` form, or pass a
    ``None`` through. One helper, so no route renders a timestamp differently
    from C4's."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return to_iso(value if value.tzinfo else value.replace(tzinfo=_UTC))


def get_engine(request: Request):
    """The read engine. Same wiring seam as C4's service: the spine sets it on
    app state. A missing engine is a 500, not an empty list — an unwired ops
    route that returns ``{"tasks": []}`` looks exactly like a quiet system."""
    engine = getattr(request.app.state, "ops_engine", None)
    if engine is None:
        engine = getattr(
            getattr(request.app.state, "approvals_service", None), "engine", None
        )
    if engine is None:
        raise RuntimeError(
            "app.state.ops_engine is not set — wire a read engine before "
            "mounting the ops router"
        )
    return engine


async def _project_keys(conn, request_ids: list[str]) -> dict[str, str | None]:
    """Q2's answer: the project comes from the ``plan_created`` event's detail.

    ONE query for the whole page. The alternative — a lookup per task — is an
    N+1 on a 10-second poll, which is the same objection §13.2 raises against
    fetching a trace per task.
    """
    if not request_ids:
        return {}
    rows = (
        await conn.execute(
            select(E.c.request_id, E.c.detail).where(
                E.c.stage == PLAN_STAGE, E.c.request_id.in_(request_ids)
            )
        )
    ).fetchall()
    out: dict[str, str | None] = {}
    for row in rows:
        detail = row.detail if isinstance(row.detail, dict) else {}
        out[row.request_id] = detail.get("project_key")
    return out


async def _approval_ids(conn, task_ids: list[str]) -> dict[str, str]:
    """§13.1's optional ``approval_id``. Batched for the same reason. The most
    recent approval per task wins — a task can park more than once over its
    life, and the dashboard's link should go to the current one."""
    if not task_ids:
        return {}
    rows = (
        await conn.execute(
            select(A.c.task_id, A.c.id, A.c.created_at)
            .where(A.c.task_id.in_(task_ids))
            .order_by(A.c.created_at.asc(), A.c.id.asc())
        )
    ).fetchall()
    return {row.task_id: row.id for row in rows}


def _task_shape(row, *, project_key: str | None, approval_id: str | None) -> dict:
    """§13.1's ``Task``, field for field."""
    return {
        "id": row.id,
        "objective": row.objective,
        "status": row.status,
        "assigned_agent": row.assigned_agent,
        "priority": row.priority,
        "project_key": project_key,
        "request_id": row.request_id,
        "conversation_id": row.conversation_id,
        "approval_id": approval_id,
        "created_at": _iso(row.created_at),
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
        "failure_kind": row.failure_kind,
    }


async def _tasks_page(conn, *, conditions: list, limit: int, cursor: str | None):
    """The shared list mechanic: C4's cursor rules, applied to ``tasks``.

    Identical to C4 §6.5 by instruction (§13: "same cursor pagination"), which
    means all three of its pinned readings hold here too — keyset on
    ``(created_at, id)``, lexicographic id tiebreak, and ``next_cursor`` null
    only on a SHORT page. A second pagination dialect in the same dashboard
    would be a bug generator.
    """
    where = list(conditions)
    if cursor is not None:
        anchor = (
            await conn.execute(select(T.c.created_at, T.c.id).where(T.c.id == cursor))
        ).first()
        if anchor is None:
            raise ApiError(422, "validation_error", f"unknown cursor: {cursor}")
        where.append(
            tuple_(T.c.created_at, T.c.id) < tuple_(anchor.created_at, anchor.id)
        )
    rows = (
        await conn.execute(
            select(T)
            .where(*where)
            .order_by(T.c.created_at.desc(), T.c.id.desc())
            .limit(limit)
        )
    ).fetchall()
    projects = await _project_keys(conn, [r.request_id for r in rows])
    approvals = await _approval_ids(conn, [r.id for r in rows])
    shaped = [
        _task_shape(
            row,
            project_key=projects.get(row.request_id),
            approval_id=approvals.get(row.id),
        )
        for row in rows
    ]
    next_cursor = shaped[-1]["id"] if len(shaped) == limit else None
    return shaped, next_cursor


def create_router() -> APIRouter:
    """§13's three read surfaces. Auth, envelope and pagination are C4's,
    imported rather than reimplemented — §13: "same auth as C4, same error
    envelope, same cursor pagination"."""
    router = APIRouter(prefix="/api/v1", tags=["ops"])

    # ------------------------------------------------------------------ #
    # §13.1 — GET /api/v1/tasks
    # ------------------------------------------------------------------ #
    @router.get("/tasks", operation_id="listTasks", summary="Task list (ops)")
    async def list_tasks(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        status: str | None = Query(default=None),
        project_key: str | None = Query(default=None),
        q: str | None = Query(default=None),
        order: str | None = Query(default=None, pattern="^(newest|oldest)$"),
        limit: int = Query(default=50, ge=1, le=200),
        cursor: str | None = Query(default=None),
    ) -> dict:
        response.headers.update(NOSNIFF)
        conditions = []
        if status is not None:
            conditions.append(T.c.status == status)
        if q is not None:
            # Substring over the objective only. `q` is user input going into a
            # LIKE: it is a bound parameter (never string-formatted), and the
            # LIKE metacharacters are escaped so a query of "100%" cannot turn
            # into a full scan that matches everything.
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            conditions.append(T.c.objective.like(f"%{escaped}%", escape="\\"))
        async with get_engine(request).connect() as conn:
            tasks, next_cursor = await _tasks_page(
                conn, conditions=conditions, limit=limit, cursor=cursor
            )
        if project_key is not None:
            # Q2: filterable only over what `plan_created.detail` can answer.
            tasks = [t for t in tasks if t["project_key"] == project_key]
        if order == "oldest":
            tasks = list(reversed(tasks))
        return {"tasks": tasks, "next_cursor": next_cursor}

    @router.get(
        "/tasks/{task_id}", operation_id="getTask", summary="One task with history"
    )
    async def get_task(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        task_id: Annotated[str, Path()],
    ) -> dict:
        """§13.1 — the detail route adds ``status_events`` from
        ``task_status_events``. FR-065 asks for a status *history*: a single
        mutable ``status`` column cannot answer it, which is why the events
        table exists and why this route reads it rather than synthesising."""
        response.headers.update(NOSNIFF)
        async with get_engine(request).connect() as conn:
            row = (await conn.execute(select(T).where(T.c.id == task_id))).first()
            if row is None:
                raise ApiError(404, "not_found", f"no task with id {task_id}")
            projects = await _project_keys(conn, [row.request_id])
            approvals = await _approval_ids(conn, [row.id])
            events = (
                await conn.execute(
                    select(S.c.from_status, S.c.to_status, S.c.at)
                    .where(S.c.task_id == task_id)
                    .order_by(S.c.at.asc(), S.c.id.asc())
                )
            ).fetchall()
        shaped = _task_shape(
            row,
            project_key=projects.get(row.request_id),
            approval_id=approvals.get(row.id),
        )
        shaped["status_events"] = [
            {
                "from_status": e.from_status,
                "to_status": e.to_status,
                "at": _iso(e.at),
            }
            for e in events
        ]
        return shaped

    # ------------------------------------------------------------------ #
    # §13.2 — GET /api/v1/activity
    # ------------------------------------------------------------------ #
    @router.get(
        "/activity", operation_id="getActivity", summary="Agent activity (ops)"
    )
    async def get_activity(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict:
        """§13.2 — ``{running, parked, recent}``, each an ``ActivityItem`` (the
        ``Task`` shape plus ``latest_stage``, ``latest_stage_at`` and
        ``latest_detail``).

        **One request, three buckets, by contract**: "the alternative — list
        tasks then fetch a trace per task — is an N+1 on a 10-second poll". So
        the latest stage for every task on the page is resolved in a single
        grouped query, not one per row.
        """
        response.headers.update(NOSNIFF)
        async with get_engine(request).connect() as conn:
            running, _ = await _tasks_page(
                conn,
                conditions=[T.c.status.in_(RUNNING_STATUSES)],
                limit=limit,
                cursor=None,
            )
            parked, _ = await _tasks_page(
                conn,
                conditions=[T.c.status.in_(PARKED_STATUSES)],
                limit=limit,
                cursor=None,
            )
            recent, _ = await _tasks_page(
                conn,
                conditions=[T.c.status.notin_(RUNNING_STATUSES + PARKED_STATUSES)],
                limit=limit,
                cursor=None,
            )
            everything = running + parked + recent
            stages = await _latest_stages(conn, [t["id"] for t in everything])
        for item in everything:
            item.update(stages.get(item["id"], _EMPTY_STAGE))
        return {"running": running, "parked": parked, "recent": recent}

    # ------------------------------------------------------------------ #
    # §13.3 — GET /api/v1/audit and /api/v1/audit/{request_id}
    # ------------------------------------------------------------------ #
    @router.get("/audit", operation_id="listAuditTurns", summary="Audit index (ops)")
    async def list_audit(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        request_id: str | None = Query(default=None),
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = Query(default=None),
        outcome: str | None = Query(default=None),
        agent: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        cursor: str | None = Query(default=None),
    ) -> dict:
        """§13.3 index — one row per TURN, aggregated from ``audit_events``.

        ``stage_count`` is the honest count of events for the turn, never padded
        to twelve: Q9's recorded default is "render whatever arrives; flag any
        count ≠ 12 in warning and never pad or hide a missing stage", so the API
        must not pad either. ``outcome`` and ``failure_kind`` come from the
        ``final_response`` event's detail (ARCHITECTURE_V1 §3.4's contracted
        keys) and are ``null`` on a turn that never reached stage 12 — which is
        exactly how an interrupted turn should read.
        """
        response.headers.update(NOSNIFF)
        conditions = []
        if request_id is not None:
            conditions.append(E.c.request_id == request_id)
        if agent is not None:
            conditions.append(E.c.actor == agent)
        if from_ is not None:
            conditions.append(E.c.at >= _parse_ts(from_, "from"))
        if to is not None:
            conditions.append(E.c.at <= _parse_ts(to, "to"))

        async with get_engine(request).connect() as conn:
            rows = (
                await conn.execute(
                    select(E).where(*conditions).order_by(E.c.at.asc(), E.c.seq.asc())
                )
            ).fetchall()

        turns: dict[str, dict] = {}
        for row in rows:
            turn = turns.setdefault(
                row.request_id,
                {
                    "request_id": row.request_id,
                    "started_at": _iso(row.at),
                    "ended_at": _iso(row.at),
                    "stage_count": 0,
                    "outcome": None,
                    "failure_kind": None,
                    "agent": row.actor,
                    "conversation_id": None,
                    "task_id": row.task_id,
                },
            )
            turn["stage_count"] += 1
            turn["ended_at"] = _iso(row.at)
            if row.task_id and not turn["task_id"]:
                turn["task_id"] = row.task_id
            if row.stage == FINAL_STAGE:
                detail = row.detail if isinstance(row.detail, dict) else {}
                turn["outcome"] = detail.get("outcome")
                turn["failure_kind"] = detail.get("failure_kind")
        ordered = sorted(
            turns.values(), key=lambda t: (t["started_at"], t["request_id"]), reverse=True
        )
        if outcome is not None:
            ordered = [t for t in ordered if t["outcome"] == outcome]
        if cursor is not None:
            ids = [t["request_id"] for t in ordered]
            if cursor not in ids:
                raise ApiError(422, "validation_error", f"unknown cursor: {cursor}")
            ordered = ordered[ids.index(cursor) + 1 :]
        page = ordered[:limit]
        next_cursor = page[-1]["request_id"] if len(page) == limit else None
        return {"turns": page, "next_cursor": next_cursor}

    @router.get(
        "/audit/{request_id}",
        operation_id="getAuditTrace",
        summary="One turn's trace (ops)",
    )
    async def get_audit_trace(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        request_id: Annotated[str, Path()],
    ) -> dict:
        """§13.3 detail — ``{events, approval_events}`` in ``seq`` order.

        ``approval_events`` is the approval episode's own chain, included
        because §10.2 (traceability row: C4 §3) requires the episode to read as
        ONE story rather than two disconnected traces: the parked turn and the
        continuation share the original ``request_id`` lineage.

        ``detail`` values are returned unmodified. §13.3's carried-forward note:
        they may contain a truncated excerpt of untrusted content (T-32), and
        the audit browser applies the same plain-text containment as the
        approval card — "no exceptions for developer-facing screens".
        """
        response.headers.update(NOSNIFF)
        async with get_engine(request).connect() as conn:
            rows = (
                await conn.execute(
                    select(E)
                    .where(E.c.request_id == request_id)
                    .order_by(E.c.seq.asc())
                )
            ).fetchall()
            if not rows:
                raise ApiError(
                    404, "not_found", f"no audit trace for request {request_id}"
                )
            approvals = (
                await conn.execute(
                    select(
                        A.c.id,
                        A.c.status,
                        A.c.tool,
                        A.c.operation,
                        A.c.created_at,
                        A.c.decided_at,
                        A.c.decided_by,
                        A.c.consumed_at,
                        A.c.task_id,
                    )
                    .where(A.c.request_id == request_id)
                    .order_by(A.c.created_at.asc(), A.c.id.asc())
                )
            ).fetchall()
        return {
            "events": [
                {
                    "seq": row.seq,
                    "stage": row.stage,
                    "actor": row.actor,
                    "summary": row.summary,
                    "detail": row.detail,
                    "at": _iso(row.at),
                    "task_id": row.task_id,
                }
                for row in rows
            ],
            "approval_events": [
                {
                    "approval_id": row.id,
                    "status": row.status,
                    "tool": row.tool,
                    "operation": row.operation,
                    "created_at": _iso(row.created_at),
                    "decided_at": _iso(row.decided_at),
                    "decided_by": row.decided_by,
                    "consumed_at": _iso(row.consumed_at),
                    "task_id": row.task_id,
                }
                for row in approvals
            ],
        }

    return router


_EMPTY_STAGE = {
    "latest_stage": None,
    "latest_stage_at": None,
    "latest_detail": {},
}


async def _latest_stages(conn, task_ids: list[str]) -> dict[str, dict]:
    """§13.2's ``latest_stage`` / ``latest_stage_at`` / ``latest_detail``, for
    every task on the page in ONE query (the N+1 §13.2 names)."""
    if not task_ids:
        return {}
    rows = (
        await conn.execute(
            select(E.c.task_id, E.c.stage, E.c.at, E.c.detail, E.c.seq)
            .where(E.c.task_id.in_(task_ids))
            .order_by(E.c.at.asc(), E.c.seq.asc())
        )
    ).fetchall()
    latest: dict[str, dict] = {}
    for row in rows:
        detail = row.detail if isinstance(row.detail, dict) else {}
        latest[row.task_id] = {
            "latest_stage": row.stage,
            "latest_stage_at": _iso(row.at),
            "latest_detail": {
                key: detail[key]
                for key in ("project_display_name", "tool", "operation")
                if key in detail
            },
        }
    return latest


def _parse_ts(value: str, field: str):
    """``?from=``/``?to=`` are ISO-8601. A bad value is a 422 in C4's envelope,
    not a 500 from deep in the driver."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ApiError(
            422, "validation_error", f"{field} must be an ISO-8601 timestamp"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_UTC)
