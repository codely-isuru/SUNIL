"""C6 §2.4 — ``GET /api/v1/audit`` and ``GET /api/v1/audit/{request_id}``.

The audit browser (``V2_DASHBOARD_SPEC.md`` §10). The index groups
``audit_events`` by ``request_id`` into one row per TURN; the detail route
splits one turn's rows into the turn's own events and the approval episode's,
so an approval reads as ONE story on one ``request_id`` (``ARCHITECTURE_V2.md``
§6 Legs 3–6, C4 §3's lineage rule) rather than two disconnected traces.

**Derivations are the contract, not conveniences.** C6 §2.4 fixes each one, and
each has a failure mode this module exists to avoid:

* ``ended_at`` is the ``final_response`` row's ``at`` and is **null while in
  flight**. "The last row I happened to see" would give every interrupted turn
  a fake end time.
* ``stage_count`` counts only the twelve NFR-020 spine names, so an approval
  episode's extra rows cannot push the view's "n of 12" reading past twelve.
* ``agent`` is ``plan_created.detail.agent`` — a contracted, trusted key — not
  ``audit_events.actor``, which is the writing component ("core") on every row.
* ``conversation_id``/``task_id`` resolve through the turn's task, and are null
  in the window before a task exists.

**Untrusted content.** ``summary`` carries an ``approval_requested`` row's C4
summary verbatim and ``detail`` may embed truncated untrusted excerpts (T-32).
Both are returned byte-faithful with ``nosniff`` — containment is the renderer's
duty (C6 §4), "no exception for developer-facing screens".
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from sqlalchemy import func, select

from sunil.api.routes.approvals import (
    NOSNIFF,
    ApiError,
    OwnerSession,
    WebClient,
)
from sunil.api.routes.ops_read_model import (
    APPROVAL_LIFECYCLE_STAGES,
    E,
    FINAL_STAGE,
    PLAN_STAGE,
    SPINE_STAGES,
    T,
    aware,
    get_engine,
    iso,
    next_cursor_for,
    parse_ts,
)

#: C6 §2.4's episode-membership marker on a continuation row's ``detail``.
RESUMED_KEY = "resumed_from_approval_id"


def _detail(row) -> dict:
    return row.detail if isinstance(row.detail, dict) else {}


def _event_shape(row) -> dict:
    """C6's ``AuditEvent``. ``summary`` and ``detail`` pass through untouched."""
    return {
        "seq": row.seq,
        "stage": row.stage,
        "actor": row.actor,
        "summary": row.summary,
        "detail": row.detail,
        "at": iso(row.at),
        "task_id": row.task_id,
    }


def _is_episode_row(row) -> bool:
    """C6 §2.4: a lifecycle kind **or** a row whose ``detail`` carries
    ``resumed_from_approval_id``. The union matters — the continuation's rows
    reuse SPINE stage names (``tool_result``, ``final_response``), so a
    stage-name-only rule would leave the second half of the episode in
    ``events`` and break the §10.2 "AFTER YOUR DECISION" segment."""
    return row.stage in APPROVAL_LIFECYCLE_STAGES or RESUMED_KEY in _detail(row)


def _derive_turn(request_id: str, rows: list) -> dict:
    """One turn from its rows (already ascending ``seq``) — C6 §2.4's table."""
    first = rows[0]
    final = next((r for r in rows if r.stage == FINAL_STAGE), None)
    plan = next((r for r in rows if r.stage == PLAN_STAGE), None)
    final_detail = _detail(final) if final is not None else {}
    return {
        "request_id": request_id,
        "started_at": aware(first.at),
        "ended_at": aware(final.at) if final is not None else None,
        "stage_count": sum(1 for r in rows if r.stage in SPINE_STAGES),
        "outcome": final_detail.get("outcome"),
        "failure_kind": final_detail.get("failure_kind"),
        "agent": _detail(plan).get("agent") if plan is not None else None,
        "conversation_id": None,
        "task_id": None,
    }


def _render_turn(turn: dict) -> dict:
    out = dict(turn)
    out["started_at"] = iso(turn["started_at"])
    out["ended_at"] = iso(turn["ended_at"])
    return out


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["audit"])

    @router.get("/audit", operation_id="listAuditTurns", summary="Audit index")
    async def list_audit_turns(
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
        """C6 §2.4 index, paginated per §2.1 on ``started_at desc,
        request_id desc``.

        ``from``/``to`` are half-open on the TURN's ``started_at``
        (``from <= started_at < to``), so they are pushed into SQL as a
        ``MIN(at)`` group filter rather than applied to individual rows — a
        row-level window would return half a turn and derive an ``ended_at``
        from a truncated set. ``outcome`` and ``agent`` live inside JSON
        ``detail`` and are filtered on the DERIVED value once the group is
        assembled; like every other filter they run BEFORE pagination (§2.1.2).
        """
        response.headers.update(NOSNIFF)
        window = []
        if from_ is not None:
            window.append(func.min(E.c.at) >= parse_ts(from_, "from"))
        if to is not None:
            window.append(func.min(E.c.at) < parse_ts(to, "to"))
        turn_ids = select(E.c.request_id).group_by(E.c.request_id).having(*window)
        if request_id is not None:
            turn_ids = turn_ids.where(E.c.request_id == request_id)

        async with get_engine(request).connect() as conn:
            rows = (
                await conn.execute(
                    select(E)
                    .where(E.c.request_id.in_(turn_ids))
                    .order_by(E.c.request_id.asc(), E.c.seq.asc())
                )
            ).fetchall()
            grouped: dict[str, list] = {}
            for row in rows:
                grouped.setdefault(row.request_id, []).append(row)
            turns = [_derive_turn(rid, rs) for rid, rs in grouped.items()]
            if turns:
                tasks = (
                    await conn.execute(
                        select(T.c.request_id, T.c.id, T.c.conversation_id).where(
                            T.c.request_id.in_([t["request_id"] for t in turns])
                        )
                    )
                ).fetchall()
                linked = {t.request_id: t for t in tasks}
                for turn in turns:
                    task = linked.get(turn["request_id"])
                    if task is not None:
                        turn["task_id"] = task.id
                        turn["conversation_id"] = task.conversation_id

        if outcome is not None:
            turns = [t for t in turns if t["outcome"] == outcome]
        if agent is not None:
            turns = [t for t in turns if t["agent"] == agent]
        # C6 §2.1.1 on the audit keys: `started_at desc, request_id desc`, the
        # id compared as a plain string.
        turns.sort(key=lambda t: (t["started_at"], t["request_id"]), reverse=True)

        if cursor is not None:
            ids = [t["request_id"] for t in turns]
            if cursor not in ids:
                # C6 §2.1.4 — never a silent page one. A cursor that is a real
                # request_id but is not in THIS filtered set is still unknown:
                # a cursor is only meaningful with the same filters held.
                raise ApiError(422, "validation_error", f"unknown cursor: {cursor}")
            turns = turns[ids.index(cursor) + 1 :]
        page = [_render_turn(t) for t in turns[:limit]]
        return {
            "turns": page,
            "next_cursor": next_cursor_for(page, limit, "request_id"),
        }

    @router.get(
        "/audit/{request_id}",
        operation_id="getAuditTurn",
        summary="One turn's events and approval episode",
    )
    async def get_audit_turn(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        request_id: Annotated[str, Path()],
    ) -> dict:
        """C6 §2.4's detail partition — ``{events, approval_events}``, both
        ascending ``seq``. ``approval_events`` is **null** (not ``[]``) when the
        turn had no episode: "no approval happened" and "an approval happened
        and produced nothing" are different facts, and §10.2 renders only the
        first as an absent segment."""
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
                404, "not_found", f"no audit turn for request {request_id}"
            )
        episode = [_event_shape(r) for r in rows if _is_episode_row(r)]
        return {
            "events": [_event_shape(r) for r in rows if not _is_episode_row(r)],
            "approval_events": episode or None,
        }

    return router
