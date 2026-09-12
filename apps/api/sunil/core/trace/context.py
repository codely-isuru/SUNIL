"""`TraceContext` — the per-turn seam every component that advances a turn
depends on, plus its two implementations.

`emit()` is the ONLY way a stage advances. There is no second path, which is
what makes "all twelve stages, in order, from stored records alone" provable
rather than aspirational. It is `async` and takes `summary` because an
`audit_events` insert needs one (`summary` is `NOT NULL`).

`NullTraceContext` records emissions in memory and never breaches its deadline —
for unit tests and for any lane building ahead of the real emitter.
`LiveTraceContext` holds the per-turn state (`request_id`, ids, monotonic start,
`seq`) and the `SUNIL_TURN_DEADLINE_S` budget, enforces at-most-once itself, and
delegates the sink writes to `core.trace.emitter.emit_stage()`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.trace.emitter import emit_stage
from sunil.core.trace.stages import TraceStage


class DuplicateStageEmission(Exception):
    """A turn tried to emit a stage a second time.

    Each of the twelve is emitted at most once per turn; this exception is what
    makes that structural rather than conventional. Retries belong in `detail`
    (`provider_attempts`, `plan_attempts`), never as a second stage event —
    otherwise `UniqueConstraint(request_id, seq)` decides the outcome and the
    failure looks like a concurrency bug.
    """


@runtime_checkable
class TraceContext(Protocol):
    """What every component that advances a turn depends on."""

    request_id: str
    user_id: str | None
    conversation_id: str | None

    async def emit(
        self,
        stage: TraceStage,
        *,
        summary: str,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        """Record that `stage` occurred for this turn, to every sink."""
        ...

    def remaining_deadline_s(self) -> float:
        """Seconds left before `SUNIL_TURN_DEADLINE_S` is breached for this turn.
        An attempt whose own timeout exceeds what remains is not started — that
        check is the difference between a deadline and a hope."""
        ...


class NullTraceContext:
    """A `TraceContext` that records in memory and never breaches its deadline."""

    def __init__(
        self,
        *,
        request_id: str = "null",
        user_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        self.request_id = request_id
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.emitted: list[tuple[TraceStage, str, dict[str, Any] | None, str | None]] = []

    async def emit(
        self,
        stage: TraceStage,
        *,
        summary: str,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.emitted.append((stage, summary, detail, task_id))

    def remaining_deadline_s(self) -> float:
        return float("inf")


class LiveTraceContext:
    """The concrete `TraceContext`."""

    def __init__(
        self,
        *,
        request_id: str,
        user_id: str | None,
        conversation_id: str | None,
        sessionmaker: async_sessionmaker[AsyncSession],
        turn_deadline_s: float,
        actor: str = "api",
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.request_id = request_id
        self.user_id = user_id
        self.conversation_id = conversation_id
        self._sessionmaker = sessionmaker
        self._turn_deadline_s = turn_deadline_s
        self._actor = actor
        self._clock = clock
        self._started_monotonic = clock()
        self._seq = 0
        self._emitted_stages: set[TraceStage] = set()
        #: What the C5 envelope's `trace[]` is built from. Kept alongside the
        #: durable rows rather than instead of them: the response reports the
        #: monotonic offsets this turn actually measured, while `audit_events`
        #: stays the record a later reader reconstructs from.
        self.entries: list[tuple[TraceStage, int, dict[str, Any] | None]] = []

    def _offset_ms(self) -> int:
        return int((self._clock() - self._started_monotonic) * 1000)

    def remaining_deadline_s(self) -> float:
        """Never negative."""
        elapsed = self._clock() - self._started_monotonic
        return max(0.0, self._turn_deadline_s - elapsed)

    async def emit(
        self,
        stage: TraceStage,
        *,
        summary: str,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        if stage in self._emitted_stages:
            raise DuplicateStageEmission(
                f"stage {stage.value!r} already emitted for request "
                f"{self.request_id!r} — retries belong in `detail` "
                "(`provider_attempts`, `plan_attempts`), never a second stage event"
            )
        self._emitted_stages.add(stage)
        self._seq += 1
        offset_ms = self._offset_ms()
        self.entries.append((stage, offset_ms, detail))

        await emit_stage(
            sessionmaker=self._sessionmaker,
            request_id=self.request_id,
            seq=self._seq,
            offset_ms=offset_ms,
            stage=stage,
            task_id=task_id,
            actor=self._actor,
            summary=summary,
            detail=detail,
        )
