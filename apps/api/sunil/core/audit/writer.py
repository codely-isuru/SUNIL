"""The audit writer — one `audit_events` row per stage.

`write_audit_event()` is what makes the ROADMAP §28 query
(`SELECT stage, seq, at FROM audit_events WHERE request_id = :rid ORDER BY seq`)
return all twelve stages, in order, for a real turn.

Two properties this function owns:

1. **Its own short-lived transaction**, independent of whatever transaction the
   request's business logic is using. An audit row must not be lost — or be only
   conditionally visible — because an unrelated later write rolled back.
2. **Unconditional redaction.** `summary` and `detail` both go through
   `sunil.redaction.scrub()` before the insert. There is no policy branch that
   can skip it, because a capture policy must never be able to suppress or
   weaken an audit row.
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
    """Insert one `audit_events` row, committing it in its own session."""
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
