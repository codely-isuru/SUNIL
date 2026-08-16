"""The audit writer — one `audit_events` row per stage (§8.1, §28).

`write_audit_event()` is the table ET-6 is graded against:
`SELECT stage, seq, at FROM audit_events WHERE request_id = :rid ORDER BY
seq` must return all twelve stages, in the enum's order, none missing, for
a request to pass. This module is what actually makes that row exist.

Every `detail` payload is passed through `sunil.redaction.scrub()` before
insert (ADR-006) — `audit_events.detail` is one of the columns ET-10
grades, and §7.3.1 is explicit that a capture policy must never be able to
suppress an audit row, so redaction (a secret-value concern) is applied
here unconditionally; there is no policy branch that could skip it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.trace.stages import TraceStage
from sunil.db.models import AuditEvent
from sunil.redaction import scrub


async def write_audit_event(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    request_id: str,
    seq: int,
    stage: TraceStage,
    task_id: str | None,
    actor: str,
    summary: str,
    detail: dict[str, Any] | None,
) -> None:
    """Insert one `audit_events` row.

    Opens and commits its own short-lived session, independent of whatever
    transaction the request's business logic (T11a/T11b) is using at the
    time — an audit row must not be lost, or only conditionally visible,
    because an unrelated later write in the same request rolls back.
    """
    scrubbed_detail = scrub(detail) if detail is not None else None

    async with sessionmaker() as session:
        session.add(
            AuditEvent(
                request_id=request_id,
                seq=seq,
                stage=stage.value,
                task_id=task_id,
                actor=actor,
                summary=scrub(summary),
                detail=scrubbed_detail,
            )
        )
        await session.commit()
