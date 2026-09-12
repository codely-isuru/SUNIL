"""The trace emitter — one function, two sinks.

`emit_stage()` is called by `LiveTraceContext.emit()` and is the single place a
stage advances:

1. a structured log line (`sunil.logging`, whose base chain scrubs it);
2. an `audit_events` row (`core.audit.writer.write_audit_event`).

A third sink — the progress/SSE bus — is where an M2 streaming lane adds its
publish, in this one function, so a stage can never be visible to a client
without also being durable.

Untrusted content (a plan's raw text, a repo name, a tool result) goes into
`detail` as a structured field, never interpolated into the log message string:
a message string is what gets grepped and pasted around, and a format-string
injection there is how "audit says" stops meaning anything.
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
    # Sink 1: the structured log line. Redaction runs via `sunil.logging`'s base
    # processor chain — not duplicated here.
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

    # Sink 2: the durable row. `offset_ms` is carried INSIDE `detail` (rather
    # than as a column) because the C5 envelope's `trace[].offset_ms` is derived
    # from the monotonic turn clock, while `audit_events.at` is wall-clock: two
    # different measurements, and the response must not silently substitute one
    # for the other. Redaction happens inside the writer, unconditionally.
    await write_audit_event(
        sessionmaker,
        request_id=request_id,
        seq=seq,
        stage=stage,
        task_id=task_id,
        actor=actor,
        summary=summary,
        detail={**(detail or {}), "offset_ms": offset_ms},
    )
