"""The trace emitter — one function, three sinks (§8.1).

`emit_stage()` is called by `LiveTraceContext.emit()` and is the single
place a stage advances:

1. a structured `structlog` log line;
2. an `audit_events` row (`core.audit.writer.write_audit_event()`);
3. a publish to the trace bus — a no-op in M1, because `core/trace/bus.py`
   is T12's file and T12 is optional/post-M1 (`SUNIL_PROGRESS_EVENTS`
   ships `false`). There is nothing to call yet; when T12 lands, this is
   the one place a `bus.publish(...)` call is added.

Untrusted content (a GitHub commit message, a plan's raw text, ...) goes
into the `detail` field, never interpolated into the log message string
itself (T-32) — the call below passes `detail` as a structured kwarg, not
as part of the `"stage_emitted"` string.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.audit.writer import write_audit_event
from sunil.core.trace.stages import TraceStage
from sunil.logging import get_logger

_logger = get_logger("sunil.trace")


async def emit_stage(
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    request_id: str,
    seq: int,
    offset_ms: int,
    stage: TraceStage,
    task_id: str | None,
    actor: str,
    summary: str,
    detail: dict[str, Any] | None,
) -> None:
    # Sink 1: the structured log line. Redaction runs on this via the
    # structlog processor chain (`sunil.logging.shared_processors`) — not
    # duplicated here.
    _logger.info(
        "stage_emitted",
        request_id=request_id,
        seq=seq,
        stage=stage.value,
        offset_ms=offset_ms,
        task_id=task_id,
        actor=actor,
        summary=summary,
        detail=detail,
    )

    # Sink 2: the durable audit_events row (redaction applied inside the
    # writer itself, unconditionally — see that module's docstring).
    await write_audit_event(
        sessionmaker,
        request_id=request_id,
        seq=seq,
        stage=stage,
        task_id=task_id,
        actor=actor,
        summary=summary,
        detail=detail,
    )

    # Sink 3: trace bus publish (SSE) — no-op until T12's `core/trace/bus.py`
    # lands. Nothing to call yet.
