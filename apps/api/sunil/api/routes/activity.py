"""C6 §2.3 — ``GET /api/v1/activity``.

The Agent activity view (``V2_DASHBOARD_SPEC.md`` §7) polled every ten seconds.
**One request for the whole snapshot, and no parameters**: the alternative —
list tasks, then fetch a trace per task — is an N+1 on a 10-second poll, which
is the exact objection C6 §2.3 records. So the three buckets are three bounded
queries and the audit fold-in is ONE more, whatever the row count.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from sunil.api.routes.approvals import NOSNIFF, OwnerSession, WebClient
from sunil.api.routes.ops_read_model import (
    E,
    LATEST_DETAIL_KEYS,
    PARKED_STATUSES,
    RECENT_CAP,
    RECENT_STATUSES,
    RUNNING_STATUSES,
    T,
    get_engine,
    iso,
    select_tasks,
)

#: C6 §2.3 — "both ``latest_*`` fields are null only if no audit row exists".
#: ``latest_detail`` is a required object, so it is an empty projection, not
#: null: "no contracted keys in the latest row" and "no latest row" are
#: different facts and the shape keeps them distinguishable.
_NO_LATEST = {"latest_stage": None, "latest_stage_at": None, "latest_detail": {}}

#: The three buckets' status sets, in response order.
_BUCKETS = (
    ("running", RUNNING_STATUSES, None),
    ("parked", PARKED_STATUSES, None),
    ("recent", RECENT_STATUSES, RECENT_CAP),
)

#: An upper bound for the unbounded buckets. C6 caps only ``recent``; running
#: and parked are "everything in that state", but an unbounded SELECT on a poll
#: endpoint is a denial-of-service waiting for a bad day, so they take the
#: pagination law's own ceiling (C6 §2.1.5's max ``limit``).
_BUCKET_CEILING = 200


async def _latest_by_request(conn, request_ids: list[str]) -> dict[str, dict]:
    """C6 §2.3's fold-in: for each ``request_id``, the HIGHEST-SEQ
    ``audit_events`` row.

    Keyed on ``request_id``, not ``task_id``: the early rows of a turn are
    written before a task exists (``message_received`` precedes
    ``plan_created``), so ``audit_events.task_id`` is null there and a task-keyed
    join would silently miss the turn's own history.

    ``seq``, not ``at``: ``seq`` is the contract's per-turn ordinal. Two rows can
    share a timestamp; only one can be the latest stage.

    ``latest_detail`` is a projection onto exactly the three contracted keys.
    Audit ``detail`` may embed truncated UNTRUSTED excerpts (``ARCHITECTURE_V1``
    §3.4, T-32), so passing the whole object through would break this endpoint's
    trusted-detail promise — C6 §2.3: "other detail keys MUST NOT pass through".
    """
    if not request_ids:
        return {}
    rows = (
        await conn.execute(
            select(E.c.request_id, E.c.stage, E.c.at, E.c.detail, E.c.seq)
            .where(E.c.request_id.in_(request_ids))
            .order_by(E.c.request_id.asc(), E.c.seq.asc())
        )
    ).fetchall()
    latest: dict[str, dict] = {}
    for row in rows:  # ordered ascending by seq, so the last write wins
        detail = row.detail if isinstance(row.detail, dict) else {}
        latest[row.request_id] = {
            "latest_stage": row.stage,
            "latest_stage_at": iso(row.at),
            "latest_detail": {
                key: detail[key] for key in LATEST_DETAIL_KEYS if key in detail
            },
        }
    return latest


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["activity"])

    @router.get(
        "/activity", operation_id="getActivity", summary="Agent activity (ops)"
    )
    async def get_activity(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
    ) -> dict:
        """C6 §2.3 — ``{running, parked, recent}``.

        The partition is on ``tasks.status`` and nothing else: ``running`` =
        ``pending`` + ``in_progress``, ``parked`` = ``parked``, ``recent`` =
        ``completed`` + ``failed`` capped at the 20 most recent. All three use
        the §2.1 order, so the cap does not depend on ``completed_at`` being set
        on failed rows — which it often is not.
        """
        response.headers.update(NOSNIFF)
        snapshot: dict[str, list[dict]] = {}
        async with get_engine(request).connect() as conn:
            for name, statuses, cap in _BUCKETS:
                snapshot[name] = await select_tasks(
                    conn,
                    conditions=[T.c.status.in_(statuses)],
                    limit=cap or _BUCKET_CEILING,
                )
            everything = [item for bucket in snapshot.values() for item in bucket]
            latest = await _latest_by_request(
                conn, sorted({item["request_id"] for item in everything})
            )
        for item in everything:
            item.update(latest.get(item["request_id"], _NO_LATEST))
        return snapshot

    return router
