"""C6 §2.2 — ``GET /api/v1/tasks`` and ``GET /api/v1/tasks/{task_id}``.

The Tasks view (``V2_DASHBOARD_SPEC.md`` §8) and the dashboard's tasks box
(§16). Read-only, owner-session only — the exact C4 lane, imported from
``routes/approvals.py`` rather than reimplemented, so there is one definition of
"owner" in the API. The ADR-035 service bearer is never valid here; it is
registered on ``POST /api/v1/chat`` alone, structurally.

Shapes, ordering and the cursor law are C6's and live in ``ops_read_model.py``;
what remains below is the query and the projection.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Query, Request, Response
from sqlalchemy import select

from sunil.api.routes.approvals import (
    NOSNIFF,
    ApiError,
    OwnerSession,
    WebClient,
)
from sunil.api.routes.ops_read_model import (
    S,
    T,
    approval_ids,
    get_engine,
    iso,
    next_cursor_for,
    select_tasks,
    task_conditions,
    task_shape,
)


def create_router() -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["tasks"])

    @router.get("/tasks", operation_id="listTasks", summary="List tasks (ops)")
    async def list_tasks(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        status: str | None = Query(default=None),
        project_key: str | None = Query(default=None),
        q: str | None = Query(default=None),
        order: str = Query(default="newest", pattern="^(newest|oldest)$"),
        limit: int = Query(default=50, ge=1, le=200),
        cursor: str | None = Query(default=None),
    ) -> dict:
        """C6 §2.2 + §2.1.

        The three filters are SQL predicates, not a post-filter over the page:
        C6 §2.1.2 makes a page walk a walk over the FILTERED set, so filtering
        after pagination would drop rows the client never gets a chance to see.

        ``order=oldest`` reverses both SORT KEYS (C6 §2.1.6), not the returned
        page — reversing a page would hand back the NEWEST rows on page one
        under an "oldest" label, which is the failure the suite pins.
        """
        response.headers.update(NOSNIFF)
        conditions = task_conditions(status=status, project_key=project_key, q=q)
        async with get_engine(request).connect() as conn:
            tasks = await select_tasks(
                conn,
                conditions=conditions,
                limit=limit,
                cursor=cursor,
                oldest=order == "oldest",
            )
        return {"tasks": tasks, "next_cursor": next_cursor_for(tasks, limit, "id")}

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
        """C6 §2.2's detail — the ``Task`` plus ``status_events`` ascending
        ``at`` (ties keep write order, hence the ``id`` tiebreak on a table whose
        id is a monotonic integer). FR-065 asks for a status *history*: a single
        mutable ``status`` column cannot answer it, which is why the events table
        exists and why this route reads it rather than synthesising a timeline.
        """
        response.headers.update(NOSNIFF)
        async with get_engine(request).connect() as conn:
            row = (await conn.execute(select(T).where(T.c.id == task_id))).first()
            if row is None:
                raise ApiError(404, "not_found", f"no task with id {task_id}")
            approvals = await approval_ids(conn, [row.id])
            events = (
                await conn.execute(
                    select(S.c.from_status, S.c.to_status, S.c.at)
                    .where(S.c.task_id == task_id)
                    .order_by(S.c.at.asc(), S.c.id.asc())
                )
            ).fetchall()
        shaped = task_shape(row, approval_id=approvals.get(row.id))
        shaped["status_events"] = [
            {"from_status": e.from_status, "to_status": e.to_status, "at": iso(e.at)}
            for e in events
        ]
        return shaped

    return router
