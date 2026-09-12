"""The database `AuditHook` — C1 §2.2's two-phase `tool_calls` record.

`attempt()` INSERTs before any handler runs; `finalise()` UPDATEs once the
pipeline resolves. Two phases rather than one because a row written only on
completion is missing for exactly the calls worth investigating: a hang, a crash,
a process killed mid-call (Security review 2026-09-10 item 3).

Both phases commit in their **own** session, independent of whatever transaction
the turn is using — the same rule the audit writer follows, for the same reason:
an audit record must not disappear because an unrelated later write rolled back.

**The two exceptions are deliberate, and they are the opposite rule** (C1 §2.1
step 4, Security wave-1 condition C-1). On the approval paths the attempt row
MUST share a transaction: with the consume CAS on a continuation, and with the
approval INSERT on a park. There, "the row survives an unrelated rollback" is the
wrong property — an approval spent without its row, or a parked approval with no
record of the call that parked it, is worse than neither. :meth:`attempt_on`
writes on the caller's connection for exactly those two moments; nothing else
uses it.

`validated_plan_id` is not a field of C1's frozen `ToolCallAttempt`, so it is
bound to the hook instance instead (ADR-004 Amendment 1's `ExecutionMetadata`):
the orchestrator mints one hook per plan execution, and every row that hook
writes carries the id of the plan that authorised the call. An agent cannot
supply it, and there is no path that writes a `tool_calls` row without one.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from sunil.core.tool_framework.base import ToolCallAttempt
from sunil.db.base import new_uuid, utc_now
from sunil.db.models import ToolCall, ToolCallOutcome
from sunil.redaction import scrub


class DbToolAuditHook:
    """C1 §2.2 `AuditHook`, persisting to `tool_calls`."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        *,
        validated_plan_id: str | None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._validated_plan_id = validated_plan_id
        #: Every attempt this hook recorded, in order. The orchestrator reads it
        #: to report the permission decision on the `permission_decision` stage —
        #: from the audited record rather than from a value the agent passed
        #: around, so the trace and the row cannot disagree.
        self.attempts: list[ToolCallAttempt] = []

    async def attempt(self, record: ToolCallAttempt) -> str:
        self.attempts.append(record)
        row_id = new_uuid()
        values = self._row_values(row_id, record)
        async with self._sessionmaker() as session:
            session.add(ToolCall(**values))
            await session.commit()
        return row_id

    async def attempt_on(self, conn: AsyncConnection, record: ToolCallAttempt) -> str:
        """The same row, written on a connection the CALLER owns — C1 §2.1 step
        4's transactional rule (Security wave-1 condition C-1).

        Used on the two paths where the row must commit with something else:
        with the consume CAS on a continuation, and with the approval INSERT on a
        park. Everything about the row is identical to :meth:`attempt`, including
        the scrubbing and the honest `not_executed` outcome; only the transaction
        it belongs to differs, and that difference is the whole control — a row
        in its own session can be lost by a crash that the CAS survives.

        Deliberately NOT a commit: the caller's transaction owns that moment.
        Core SQL rather than a session bound to the connection, because a nested
        ORM session would be a second unit of work inside somebody else's
        transaction with its own flush ordering.
        """
        row_id = new_uuid()
        await conn.execute(ToolCall.__table__.insert().values(**self._row_values(row_id, record)))
        self.attempts.append(record)
        return row_id

    def _row_values(self, row_id: str, record: ToolCallAttempt) -> dict:
        """One projection of a `ToolCallAttempt` onto a `tool_calls` row, shared
        by both writers — a second copy is how the transactional path and the
        ordinary one start describing the same call differently."""
        return {
            "id": row_id,
            "request_id": record.request_id,
            "task_id": record.task_id,
            "validated_plan_id": self._validated_plan_id,
            "agent_id": record.agent_id,
            "tool": record.tool,
            "operation": record.operation,
            "adapter_kind": (
                record.adapter_kind.value if record.adapter_kind is not None else None
            ),
            "server_id": record.server_id,
            "args_hash": record.args_hash,
            # Params are tool input, which can embed anything the owner (or an
            # untrusted upstream) put in the turn.
            "params_redacted": (
                scrub(record.params_redacted) if record.params_redacted is not None else None
            ),
            "permission_decision": (
                record.permission_decision.value
                if record.permission_decision is not None
                else None
            ),
            "permission_reason": (
                scrub(record.permission_reason) if record.permission_reason is not None else None
            ),
            "approval_id": record.approval_id,
            # Not executed YET — the honest value for a row written before the
            # handler runs.
            "outcome": ToolCallOutcome.NOT_EXECUTED.value,
            "created_at": utc_now(),
        }

    async def finalise(
        self,
        audit_id: str,
        *,
        outcome: Literal["ok", "error"],
        error_kind: str | None,
        duration_ms: int,
    ) -> None:
        async with self._sessionmaker() as session:
            row = await session.get(ToolCall, audit_id)
            if row is None:  # pragma: no cover - only if attempt() never ran
                return
            row.outcome = outcome
            row.error_kind = error_kind
            row.duration_ms = duration_ms
            row.finalised_at = utc_now()
            await session.commit()
