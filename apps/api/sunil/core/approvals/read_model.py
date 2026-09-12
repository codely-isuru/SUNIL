"""The approvals READ model — C4's two GET routes as database queries.

**Why this module exists.** C4 §4's frozen ``ApprovalsService`` protocol declares
exactly two methods, ``park`` and ``consume``, and C4 §1 names their single
caller: the Tool Manager. The HTTP surface's two reads (``GET /api/v1/approvals``
and ``GET /api/v1/approvals/{id}``) are not on that seam — ``get`` is not in the
contract at all — so a route that awaited them off the injected service demanded
methods no conformant implementation has to provide, and 500'd on the ones that
provide them synchronously (QA wave-1 finding B1).

C6 had the same problem and solved it the other way round: its three route
modules read the spine's tables through ``api/routes/ops_read_model.py`` instead
of growing service methods. This module is that precedent applied to the
``approvals`` table, and the same rules hold:

* **read-only, structurally** — every statement here is a ``SELECT`` issued on a
  ``connect()`` connection, so there is no transaction for an accidental write to
  commit into. The mutating path (``decide``) stays on the service layer, where
  C4 §6.2 puts it normatively, because it is a compare-and-swap and a second
  implementation of a transition is a second way to lose one;
* **``continuation`` is not selectable here** — :data:`ROW_COLUMNS` lists the
  projection explicitly, so C4 §4's "never leaves this service over HTTP" is a
  property of the query rather than a habit of its callers;
* **one query per read, not two.** ``DatabaseApprovalsService.list_approvals`` and
  ``.get`` delegate to these functions, so the service and the route return the
  same rows in the same order by construction — the read model is shared, not
  duplicated.

Untrusted values (``summary``, every ``params_redacted`` value) are returned
byte-faithful: containment is the dashboard's rendering duty (C4 §4, Security
review item 8), and a server that "helpfully" escaped would corrupt the value the
owner is entitled to inspect.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sunil.core.approvals.base import (
    Approval,
    ApprovalListResponse,
    ApprovalStatus,
)
from sunil.core.approvals.table import approvals_table as T

#: The columns the HTTP-facing ``Approval`` model is built from. ``continuation``
#: is deliberately NOT among them (C4 §4).
ROW_COLUMNS = (
    T.c.id,
    T.c.status,
    T.c.created_at,
    T.c.expires_at,
    T.c.agent_id,
    T.c.tool,
    T.c.operation,
    T.c.args_hash,
    T.c.params_redacted,
    T.c.request_id,
    T.c.conversation_id,
    T.c.task_id,
    T.c.summary,
    T.c.decided_at,
    T.c.decided_by,
    T.c.decision_reason,
    T.c.consumed_at,
)


def to_iso(moment: datetime) -> str:
    """The contract's ISO-8601 UTC form (``…Z``), whole seconds."""
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def aware(moment: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes even from a ``timezone=True`` column;
    Postgres hands back aware ones. Normalised once, at the edge."""
    if moment is None:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _stamp(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else to_iso(aware(value))


def approval_from_row(row: Any) -> Approval:
    """One result row → C4's ``Approval``. The single mapper: the service's
    ``decide`` RETURNING clause, the list and the detail all render a row the
    same way, so no path can invent a second timestamp format."""
    return Approval(
        id=row.id,
        status=ApprovalStatus(row.status),
        created_at=_stamp(row.created_at),
        expires_at=_stamp(row.expires_at),
        agent_id=row.agent_id,
        tool=row.tool,
        operation=row.operation,
        args_hash=row.args_hash,
        params_redacted=row.params_redacted,
        request_id=row.request_id,
        conversation_id=row.conversation_id,
        task_id=row.task_id,
        summary=row.summary,
        decided_at=_stamp(row.decided_at),
        decided_by=row.decided_by,
        decision_reason=row.decision_reason,
        consumed_at=_stamp(row.consumed_at),
    )


async def get_approval(conn: AsyncConnection, approval_id: str) -> Approval | None:
    """C4's detail read. ``None`` is the route's 404 and the service's ``None``."""
    row = (
        await conn.execute(select(*ROW_COLUMNS).where(T.c.id == approval_id))
    ).first()
    return None if row is None else approval_from_row(row)


async def list_approvals(
    conn: AsyncConnection,
    *,
    status: ApprovalStatus | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> ApprovalListResponse:
    """C4 §6.5's law, as one keyset query.

    Ordering is ``created_at`` desc then ``id`` desc, with ``id`` compared
    lexicographically — the plain meaning of ordering a string column, and safe
    because every id the service mints is ``apr-`` + a 26-character
    Crockford-base32 ULID (one alphabet, one width, so byte order and collation
    order cannot disagree).

    ``next_cursor`` is ``None`` ONLY for a short page. An exactly-full final page
    still returns a cursor and the client learns it is done from the following
    empty page — no look-ahead query, which is why the contract was pinned this
    way (QA finding F8).

    An unknown cursor raises ``ValueError`` (the route maps it to 422) rather
    than silently serving page one, which would make a paging loop restart for
    ever.
    """
    conditions = []
    if status is not None:
        conditions.append(T.c.status == ApprovalStatus(status).value)

    if cursor is not None:
        anchor = (
            await conn.execute(select(T.c.created_at, T.c.id).where(T.c.id == cursor))
        ).first()
        if anchor is None:
            raise ValueError(f"unknown cursor: {cursor}")
        conditions.append(
            tuple_(T.c.created_at, T.c.id) < tuple_(anchor.created_at, anchor.id)
        )

    rows = (
        await conn.execute(
            select(*ROW_COLUMNS)
            .where(*conditions)
            .order_by(T.c.created_at.desc(), T.c.id.desc())
            .limit(limit)
        )
    ).fetchall()

    page = [approval_from_row(row) for row in rows]
    return ApprovalListResponse(
        approvals=page, next_cursor=page[-1].id if len(page) == limit else None
    )


async def get_approval_on(engine: AsyncEngine, approval_id: str) -> Approval | None:
    """:func:`get_approval` on its own read connection."""
    async with engine.connect() as conn:
        return await get_approval(conn, approval_id)


async def list_approvals_on(
    engine: AsyncEngine,
    *,
    status: ApprovalStatus | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> ApprovalListResponse:
    """:func:`list_approvals` on its own read connection."""
    async with engine.connect() as conn:
        return await list_approvals(conn, status=status, limit=limit, cursor=cursor)
