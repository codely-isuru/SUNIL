"""The C6 §6 fixture, seeded into a real database.

C6 §6 specifies the fixture against the QA *fake* (``tests/fakes/fake_ops_store.py``,
not Stream D's to write). Stream D's routes read a database, so the same fixture
is expressed here as rows: 12 tasks covering every status (with the deliberate
``task-9``/``task-10`` equal-``created_at`` tie and the byte-fidelity objective),
21 further terminal tasks for the recent-cap probe, and the three audit turns
``req-full`` / ``req-parked`` / ``req-live``.

Keeping it in its own module means the C6 suite reads as assertions about the
contract rather than 200 lines of INSERT, and the same seed backs the SQLite and
Postgres legs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sunil.api.routes.ops_read_model import (
    OPS_METADATA,
    audit_events_table,
    task_status_events_table,
    tasks_table,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)

#: C6 §4's byte-fidelity probe value — HTML, markdown and a URL in one string.
#: If any layer sanitises, escapes or strips, this comes back different.
UNTRUSTED_OBJECTIVE = '<b>bold</b> [x](http://x.invalid) & "quoted" <script>'

#: request_id → (conversation_id) for the three seeded turns' tasks.
TURN_TASKS = {"req-full": "task-1", "req-live": "task-2", "req-parked": "task-5"}


def _at(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _task(
    n: int,
    *,
    status: str,
    created_s: int,
    objective: str | None = None,
    project_key: str | None = None,
    request_id: str | None = None,
    failure_kind: str | None = None,
) -> dict:
    return {
        "id": f"task-{n}",
        "objective": objective if objective is not None else f"objective {n}",
        "status": status,
        "assigned_agent": "project_manager",
        "priority": "normal",
        "project_key": project_key,
        "request_id": request_id or f"req-t{n}",
        "conversation_id": f"conv-{n}",
        "created_at": _at(created_s),
        "started_at": _at(created_s) if status != "pending" else None,
        "completed_at": _at(created_s + 50)
        if status in ("completed", "failed")
        else None,
        "failure_kind": failure_kind,
    }


def task_rows() -> list[dict]:
    """33 tasks. ``created_at`` = T0 + n seconds, EXCEPT ``task-10`` which shares
    ``task-9``'s timestamp — C6 §6's deliberate lexicographic tie."""
    rows = [
        _task(1, status="pending", created_s=1, objective="Refund AUD 240.00",
              project_key="sunil", request_id="req-full"),
        _task(2, status="in_progress", created_s=2, project_key="easyclean",
              request_id="req-live"),
        _task(3, status="completed", created_s=3),
        _task(4, status="failed", created_s=4, project_key="sunil",
              failure_kind="provider_error"),
        _task(5, status="parked", created_s=5, objective=UNTRUSTED_OBJECTIVE,
              project_key="sunil", request_id="req-parked"),
        _task(6, status="completed", created_s=6, project_key="easyclean"),
        _task(7, status="failed", created_s=7, failure_kind="tool_failed"),
        _task(8, status="parked", created_s=8),
        _task(9, status="pending", created_s=9),
        # The tie: same created_at as task-9, so only the id breaks it.
        _task(10, status="in_progress", created_s=9),
        _task(11, status="completed", created_s=11),
        _task(12, status="pending", created_s=12),
    ]
    # 21 further terminal tasks — one more than `recent`'s cap of 20 (C6 §2.3).
    rows += [_task(n, status="completed", created_s=n) for n in range(13, 34)]
    return rows


def status_event_rows() -> list[dict]:
    """``task-3``'s timeline — creation event first, ``from_status`` null."""
    return [
        {"task_id": "task-3", "from_status": None, "to_status": "pending",
         "at": _at(3)},
        {"task_id": "task-3", "from_status": "pending", "to_status": "in_progress",
         "at": _at(4)},
        {"task_id": "task-3", "from_status": "in_progress", "to_status": "completed",
         "at": _at(53)},
    ]


SPINE = [
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
]
PLAN_CREATED = "plan_created"


def _row(request_id, seq, stage, *, at, detail=None, summary="", task_id=None):
    return {
        "request_id": request_id,
        "seq": seq,
        "stage": stage,
        "task_id": task_id,
        "actor": "core",
        "summary": summary,
        "detail": detail,
        "at": at,
    }


def audit_rows() -> list[dict]:
    """Three turns. ``req-full`` = twelve spine rows; ``req-parked`` = eight spine
    rows + a four-row approval episode (two of which are continuation rows with
    SPINE stage names, carrying ``resumed_from_approval_id``); ``req-live`` = five
    spine rows and no ``final_response``."""
    rows: list[dict] = []

    # --- req-full: the complete twelve-stage turn -------------------------- #
    for i, stage in enumerate(SPINE, start=1):
        detail = None
        if stage == "plan_created":
            detail = {"agent": "project_manager", "project_key": "sunil"}
        elif stage == "final_response":
            detail = {"outcome": "ok", "failure_kind": None}
        rows.append(_row("req-full", i, stage, at=_at(100 + i), detail=detail,
                         task_id="task-1"))

    # --- req-parked: spine rows + the approval episode --------------------- #
    for i, stage in enumerate(SPINE[:8], start=1):
        detail = {"agent": "developer"} if stage == "plan_created" else None
        rows.append(_row("req-parked", i, stage, at=_at(200 + i), detail=detail,
                         task_id="task-5"))
    rows.append(
        _row("req-parked", 9, "approval_requested", at=_at(209),
             summary=UNTRUSTED_OBJECTIVE, detail={"approval_id": "apr-1"},
             task_id="task-5")
    )
    rows.append(
        _row("req-parked", 10, "approval_approved", at=_at(210),
             detail={"approval_id": "apr-1"}, task_id="task-5")
    )
    # The continuation. Spine stage NAMES (so they count toward stage_count)
    # but episode membership via `resumed_from_approval_id` — C6 §2.4/test 8.
    rows.append(
        _row("req-parked", 11, "tool_result", at=_at(211),
             detail={"resumed_from_approval_id": "apr-1", "tool": "stripe_mcp"},
             task_id="task-5")
    )
    rows.append(
        _row("req-parked", 12, "final_response", at=_at(212),
             detail={"resumed_from_approval_id": "apr-1", "outcome": "ok",
                     "failure_kind": None},
             task_id="task-5")
    )

    # --- req-live: in flight ---------------------------------------------- #
    # Five spine rows and no `final_response`. `plan_created` is the LAST of
    # them on purpose: it is both the highest-seq row (activity's fold-in) and
    # the source of the turn's `agent`.
    live_stages = SPINE[:4] + [PLAN_CREATED]
    for i, stage in enumerate(live_stages, start=1):
        detail = None
        if stage == "plan_created":
            # The projection probe: two contracted keys and one that must NOT
            # pass through (C6 §2.3 / test 5).
            detail = {
                "agent": "developer",
                "project_display_name": "SUNIL",
                "secret_excerpt": "sk-must-not-leak",
            }
        rows.append(_row("req-live", i, stage, at=_at(300 + i), detail=detail,
                         task_id="task-2"))
    return rows


async def seed(engine) -> None:
    """Create the read model's tables and insert the whole fixture."""
    async with engine.begin() as conn:
        await conn.run_sync(OPS_METADATA.drop_all)
        await conn.run_sync(OPS_METADATA.create_all)
        await conn.execute(tasks_table.insert(), task_rows())
        await conn.execute(task_status_events_table.insert(), status_event_rows())
        await conn.execute(audit_events_table.insert(), audit_rows())
