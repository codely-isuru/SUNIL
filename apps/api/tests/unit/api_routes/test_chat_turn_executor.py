"""`sunil.api.routes.chat` — the `TurnExecutor` Protocol and its stub
(T11a). `ARCHITECTURE_V1.md` §2 T11a: "the turn executor is behind a
Protocol with a stub implementation returning `failure.kind =
plan_rejected`, so the endpoint is real, testable and integrable before
T11b exists."
"""

from __future__ import annotations

from sunil.api.routes.chat import StubTurnExecutor, TurnExecutor
from sunil.core.trace.context import NullTraceContext


async def test_stub_turn_executor_always_returns_plan_rejected() -> None:
    executor = StubTurnExecutor()
    trace = NullTraceContext(request_id="req-1")

    result = await executor.run_turn(
        request_id="req-1",
        user_id="user-1",
        conversation_id="conv-1",
        message="Check on Sample Project.",
        trace=trace,
    )

    assert result.outcome == "failed"
    assert result.failure_kind == "plan_rejected"
    assert result.task_id is None
    assert result.assistant_content is None
    assert result.known_projects is None


async def test_stub_turn_executor_satisfies_the_turn_executor_protocol() -> None:
    executor = StubTurnExecutor()

    assert isinstance(executor, TurnExecutor)
