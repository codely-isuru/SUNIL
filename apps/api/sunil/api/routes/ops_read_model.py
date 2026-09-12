"""The read model and the one pagination law behind C6's three route modules.

**Why this module exists.** ``ARCHITECTURE_V2.md`` §2 Amendment 1 names three
route modules — ``tasks.py``, ``activity.py``, ``audit.py``. All three read the
same three spine tables and all three obey ONE ordering/pagination law (C6 §2.1,
which is C4 §6.5's law as QA pinned it in F8). Duplicating the table
declarations and the keyset predicate across three modules is how a codebase
ends up with two pagination dialects, which is precisely what C6 §2.1 exists to
prevent. So the shared parts live here and the route modules stay thin
projections.

**Read-only, and structurally so.** Every statement built here is a ``SELECT``
and the routes take a ``connect()`` (not ``begin()``) connection, so an
accidental write has no transaction to commit into. C6 §1: "no mutating verb
exists on this surface".

**Whose tables these are.** ``tasks``, ``task_status_events`` and
``audit_events`` belong to the spine lane's base schema (``ARCHITECTURE_V1.md``
§7.3, carried into V2); Stream D only reads them. They are declared here as a
read model on a private ``MetaData``, so this module compiles and is testable in
a worktree that has no ``db/models.py`` yet; at integration the spine's real
table objects supersede these declarations (same names, same columns). Only the
columns C6's shapes need are declared — a read model that mirrors every column
invites someone to read one that is not in a contract.

**``tasks.project_key`` (C6 §3, the Q2 ruling).** A real nullable column,
written once at task creation from the ``ValidatedPlan`` and never updated. It
is declared here because C6's ``Task`` shape and the ``?project_key=`` filter
both require it; the DDL that adds it to the spine's base ``tasks`` table is the
spine lane's migration, not Stream D's (Stream D's own revision owns the
``approvals`` table alone). Deriving the value per row from
``audit_events.detail`` instead — the pre-C6 reading — is the N+1-on-a-poll C6
§3 rejects, and it cannot answer for a task whose plan event is absent.

**Untrusted content is returned byte-faithful.** ``Task.objective``,
``AuditEvent.summary`` and every ``detail`` value may embed attacker-influenced
text (C6 §4, ``ARCHITECTURE_V1.md`` §3.4 T-32). Nothing in this module or its
callers sanitises, escapes or strips them: containment is a *rendering* duty, and
a server that "helpfully" encoded would hide the raw value the owner is entitled
to inspect.
"""

from __future__ import annotations

from datetime import UTC as _UTC
from datetime import datetime
from typing import Any

from fastapi import Request
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    func,
    select,
    tuple_,
)

from sunil.api.routes.approvals import ApiError
from sunil.core.approvals.service import to_iso
from sunil.core.approvals.table import approvals_table

#: Stream D's private read model over the spine's tables — see the docstring.
OPS_METADATA = MetaData()

#: ``ARCHITECTURE_V1`` §7.3 ``tasks`` + C6 §3's ``project_key``.
tasks_table = Table(
    "tasks",
    OPS_METADATA,
    Column("id", String(64), primary_key=True),
    Column("objective", String, nullable=False),
    Column("status", String(32), nullable=False),
    Column("assigned_agent", String(128), nullable=True),
    Column("priority", String(32), nullable=True),
    Column("project_key", String(128), nullable=True),
    Column("request_id", String(64), nullable=False),
    Column("conversation_id", String(64), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
    Column("failure_kind", String(64), nullable=True),
)

#: ``task_status_events`` — C6 §2.2's ``status_events`` timeline.
task_status_events_table = Table(
    "task_status_events",
    OPS_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", String(64), nullable=False),
    Column("from_status", String(32), nullable=True),
    Column("to_status", String(32), nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
)

#: ``audit_events`` — the raw material for activity's fold-in and for C6 §2.4.
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

T = tasks_table
S = task_status_events_table
E = audit_events_table
A = approvals_table

#: C6's ``TaskStatus`` enum — the M1 four plus V2's ``parked`` (ADR-031).
#: A value outside it is 422, never an empty list: an unknown status that
#: quietly matched nothing would read to the owner as "no such tasks".
TASK_STATUSES = frozenset(
    {"pending", "in_progress", "completed", "failed", "parked"}
)

#: C6 §2.3's partition of that enum.
RUNNING_STATUSES = ("pending", "in_progress")
PARKED_STATUSES = ("parked",)
RECENT_STATUSES = ("completed", "failed")
#: C6 §2.3 / spec §7.1 — ``recent`` is capped AFTER ordering.
RECENT_CAP = 20

#: The twelve NFR-020 spine stage names (``M1_BUILD_PLAN.md``; ADR-023: the spine
#: does not grow). ``stage_count`` counts these and nothing else, so the audit
#: view's "n of 12" reading stays honest when an approval episode adds rows.
SPINE_STAGES = frozenset(
    {
        "message_received",
        "context_loaded",
        "memory_retrieved",
        "model_selected",
        "llm_io",
        "plan_created",
        "agent_started",
        "tool_requested",
        "permission_decision",
        "tool_result",
        "agent_result",
        "final_response",
    }
)

#: C6 §2.4's approval lifecycle kinds. Membership of the episode is this set
#: UNION "detail carries ``resumed_from_approval_id``" — the continuation rows
#: reuse SPINE stage names, so a stage-name-only rule would miss them.
APPROVAL_LIFECYCLE_STAGES = frozenset(
    {
        "approval_requested",
        "approval_approved",
        "approval_refused",
        "approval_expired",
        "continuation_reconciled",
    }
)

FINAL_STAGE = "final_response"
PLAN_STAGE = "plan_created"

#: C6 §2.3's projection. Exactly these keys pass; everything else in an audit
#: ``detail`` may be an untrusted excerpt and must not reach this endpoint.
LATEST_DETAIL_KEYS = ("project_display_name", "tool", "operation")


def iso(value: Any) -> str | None:
    """One timestamp renderer for every C6 field, so no route invents a second
    format. Naive values are read as UTC (SQLite hands back naive datetimes)."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return to_iso(value if value.tzinfo else value.replace(tzinfo=_UTC))


def aware(value: datetime | None) -> datetime | None:
    """UTC-normalise a database timestamp for comparison/sorting in Python."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=_UTC)


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
            "mounting the ops routers"
        )
    return engine


def parse_ts(value: str, field: str) -> datetime:
    """``?from=``/``?to=`` are ISO-8601. A bad value is a 422 in C4's envelope,
    not a 500 from deep in the driver."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ApiError(
            422, "validation_error", f"{field} must be an ISO-8601 timestamp"
        ) from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_UTC)


def like_escaped(value: str) -> str:
    """``q`` is user input going into a LIKE. It is always a bound parameter
    (never string-formatted), and the LIKE metacharacters are escaped so a query
    of "100%" cannot turn into a scan that matches everything."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def objective_matches(q: str):
    """C6 §2.2's ``q``: **case-insensitive** substring over ``objective``.
    ``LIKE`` is case-insensitive for ASCII on SQLite but case-SENSITIVE on
    Postgres, so the fold is explicit on both sides rather than inherited from
    whichever database happens to be underneath."""
    return func.lower(T.c.objective).like(
        f"%{like_escaped(q.lower())}%", escape="\\"
    )


def task_conditions(
    *, status: str | None, project_key: str | None, q: str | None
) -> list:
    """C6 §2.2's AND-composing filters, built as SQL so they apply BEFORE
    ordering and pagination (C6 §2.1.2 — a page walk is a walk over the
    FILTERED set; filtering a page after the fact silently drops rows)."""
    conditions = []
    if status is not None:
        if status not in TASK_STATUSES:
            raise ApiError(
                422, "validation_error", f"unknown status: {status}"
            )
        conditions.append(T.c.status == status)
    if project_key is not None:
        conditions.append(T.c.project_key == project_key)
    if q is not None:
        conditions.append(objective_matches(q))
    return conditions


async def _project_free_keyset(conn, cursor: str, *, oldest: bool):
    """The C6 §2.1.2 cursor predicate: rows strictly after the cursor row in the
    CURRENT order. Expressed as a row-value comparison on ``(created_at, id)``,
    which compares ``id`` as a plain string — the lexicographic reading C6
    §2.1.1 pins (``task-9`` above ``task-10``)."""
    anchor = (
        await conn.execute(select(T.c.created_at, T.c.id).where(T.c.id == cursor))
    ).first()
    if anchor is None:
        raise ApiError(422, "validation_error", f"unknown cursor: {cursor}")
    pair = tuple_(T.c.created_at, T.c.id)
    anchor_pair = tuple_(anchor.created_at, anchor.id)
    return pair > anchor_pair if oldest else pair < anchor_pair


def next_cursor_for(page: list, limit: int, key: str) -> str | None:
    """C6 §2.1.3, the whole rule: ``next_cursor`` is null ONLY when the page is
    SHORT. An exactly-full final page returns a cursor and the client learns it
    is done from the following empty page — no look-ahead query."""
    return page[-1][key] if len(page) == limit else None


async def approval_ids(conn, task_ids: list[str]) -> dict[str, str]:
    """C6 §2.2's ``approval_id`` — the only C4 field C6 carries. Batched for the
    whole page (the N+1-on-a-10-second-poll objection again). A task can park
    more than once over its life; the most recent approval wins, because that is
    the one the dashboard's link should open."""
    if not task_ids:
        return {}
    rows = (
        await conn.execute(
            select(A.c.task_id, A.c.id)
            .where(A.c.task_id.in_(task_ids))
            .order_by(A.c.created_at.asc(), A.c.id.asc())
        )
    ).fetchall()
    return {row.task_id: row.id for row in rows}


def task_shape(row, *, approval_id: str | None) -> dict:
    """C6's ``Task``, field for field. Every key always present; absence is
    null (house style, the C5 envelope)."""
    return {
        "id": row.id,
        "objective": row.objective,
        "status": row.status,
        "assigned_agent": row.assigned_agent,
        "priority": row.priority,
        "project_key": row.project_key,
        "request_id": row.request_id,
        "conversation_id": row.conversation_id,
        "approval_id": approval_id,
        "created_at": iso(row.created_at),
        "started_at": iso(row.started_at),
        "completed_at": iso(row.completed_at),
        "failure_kind": row.failure_kind,
    }


async def select_tasks(
    conn,
    *,
    conditions: list,
    limit: int,
    cursor: str | None = None,
    oldest: bool = False,
) -> list[dict]:
    """The shared list mechanic: C6 §2.1's law applied to ``tasks``. Used by the
    tasks list AND by activity's three buckets, so the dashboard cannot end up
    with two orderings of the same rows."""
    where = list(conditions)
    if cursor is not None:
        where.append(await _project_free_keyset(conn, cursor, oldest=oldest))
    order = (
        (T.c.created_at.asc(), T.c.id.asc())
        if oldest
        else (T.c.created_at.desc(), T.c.id.desc())
    )
    rows = (
        await conn.execute(select(T).where(*where).order_by(*order).limit(limit))
    ).fetchall()
    approvals = await approval_ids(conn, [r.id for r in rows])
    return [task_shape(row, approval_id=approvals.get(row.id)) for row in rows]
