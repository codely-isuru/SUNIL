"""The `TraceContext` interface.

T1 owns the *interface* only — the `Protocol` below and `NullTraceContext`.
The concrete implementation (holding `request_id`, `user_id`,
`conversation_id`, `started_at`, `seq`, and the §5.3 turn deadline; writing
to the three sinks — log line, `audit_events` row, trace bus) is T4's build
(`docs/M1_BUILD_PLAN.md` §2 T4), landing in this same file.

This split exists so BE-2 (T6's Model Router, T8's tool framework) can be
written and unit-tested against `NullTraceContext` from hour two, without
waiting for T4's emitter — only their *integration* tests need T4 merged
(`docs/M1_BUILD_PLAN.md` §1.2 note).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from sunil.core.trace.stages import TraceStage


@runtime_checkable
class TraceContext(Protocol):
    """What every component that advances a turn depends on.

    `emit()` is the *only* way a stage advances (ARCHITECTURE_V1.md §3.4) —
    there is no second path, which is what makes ET-6 provable rather than
    aspirational.
    """

    request_id: str
    user_id: str | None
    conversation_id: str | None

    def emit(self, stage: TraceStage, *, detail: dict[str, Any] | None = None) -> None:
        """Record that `stage` occurred for this turn.

        Implementations write to every configured sink. Each stage must be
        emitted at most once per turn (§3.4) — retries belong in `detail`.
        """
        ...

    def remaining_deadline_s(self) -> float:
        """Seconds left before `SUNIL_TURN_DEADLINE_S` is breached for this
        turn (§5.3). The Model Router (T6) and the tool framework (T8) must
        check this before starting any attempt: an attempt whose own
        timeout exceeds what remains is not started.
        """
        ...


class NullTraceContext:
    """A `TraceContext` that records emissions in memory and never breaches
    its deadline. Used by unit tests, and by any lane building ahead of
    T4's real emitter.
    """

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
        self.emitted: list[tuple[TraceStage, dict[str, Any] | None]] = []

    def emit(self, stage: TraceStage, *, detail: dict[str, Any] | None = None) -> None:
        self.emitted.append((stage, detail))

    def remaining_deadline_s(self) -> float:
        return float("inf")
