"""`sunil.api.routes.chat.handle_chat_turn` (T11a) — the core turn
orchestration, independent of how the session/trace context were
constructed (no FastAPI, no `create_app`, no app wiring at all — see
`chat.py`'s own module docstring for why that split matters right now).

Exercised only against `StubTurnExecutor` on this branch — T11b wires in
the real executor without needing to change this function.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sunil.api.routes.chat import StubTurnExecutor, handle_chat_turn
from sunil.core.trace.context import NullTraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.models import User


async def test_stub_turn_is_recorded_as_a_plan_rejected_failure(
    session: AsyncSession, user: User
) -> None:
    trace = NullTraceContext(request_id="req-1")

    response = await handle_chat_turn(
        session,
        trace,
        executor=StubTurnExecutor(),
        user_id=user.id,
        request_id="req-1",
        message="Check on Sample Project.",
        conversation_id=None,
    )

    assert response.request_id == "req-1"
    assert response.outcome == "failed"
    assert response.message is None
    assert response.task is None
    assert response.failure is not None
    assert response.failure.kind == "plan_rejected"


async def test_handle_chat_turn_creates_a_conversation_when_none_is_given(
    session: AsyncSession, user: User
) -> None:
    trace = NullTraceContext(request_id="req-1")

    response = await handle_chat_turn(
        session,
        trace,
        executor=StubTurnExecutor(),
        user_id=user.id,
        request_id="req-1",
        message="hello",
        conversation_id=None,
    )

    assert response.conversation_id  # a real id was minted


async def test_handle_chat_turn_reuses_an_existing_conversation(
    session: AsyncSession, user: User
) -> None:
    from sunil.core.conversations.gateway import get_or_create_conversation

    conversation = await get_or_create_conversation(session, user_id=user.id, conversation_id=None)
    trace = NullTraceContext(request_id="req-1")

    response = await handle_chat_turn(
        session,
        trace,
        executor=StubTurnExecutor(),
        user_id=user.id,
        request_id="req-1",
        message="hello again",
        conversation_id=conversation.id,
    )

    assert response.conversation_id == conversation.id


async def test_handle_chat_turn_persists_the_user_message_regardless_of_outcome(
    session: AsyncSession, user: User
) -> None:
    from sqlalchemy import select
    from sunil.db.models import Message

    trace = NullTraceContext(request_id="req-1")

    response = await handle_chat_turn(
        session,
        trace,
        executor=StubTurnExecutor(),
        user_id=user.id,
        request_id="req-1",
        message="Check on Sample Project.",
        conversation_id=None,
    )

    result = await session.execute(
        select(Message).where(Message.conversation_id == response.conversation_id)
    )
    messages = list(result.scalars().all())
    assert len(messages) == 1
    assert messages[0].role == "user"
    assert messages[0].content == "Check on Sample Project."


async def test_handle_chat_turn_emits_stages_one_two_three_and_twelve_even_on_failure(
    session: AsyncSession, user: User
) -> None:
    trace = NullTraceContext(request_id="req-1")

    await handle_chat_turn(
        session,
        trace,
        executor=StubTurnExecutor(),
        user_id=user.id,
        request_id="req-1",
        message="hello",
        conversation_id=None,
    )

    emitted_stages = [stage for stage, _summary, _detail, _task in trace.emitted]
    assert emitted_stages == [
        TraceStage.MESSAGE_RECEIVED,
        TraceStage.CONTEXT_LOADED,
        TraceStage.MEMORY_RETRIEVED,
        TraceStage.FINAL_RESPONSE,
    ]


async def test_handle_chat_turn_final_response_detail_carries_outcome_and_failure_kind(
    session: AsyncSession, user: User
) -> None:
    trace = NullTraceContext(request_id="req-1")

    await handle_chat_turn(
        session,
        trace,
        executor=StubTurnExecutor(),
        user_id=user.id,
        request_id="req-1",
        message="hello",
        conversation_id=None,
    )

    final_response_emission = trace.emitted[-1]
    _stage, _summary, detail, _task_id = final_response_emission
    assert detail == {"outcome": "failed", "failure_kind": "plan_rejected"}


async def test_handle_chat_turn_response_includes_zero_usage_when_no_llm_calls_were_made(
    session: AsyncSession, user: User
) -> None:
    trace = NullTraceContext(request_id="req-1")

    response = await handle_chat_turn(
        session,
        trace,
        executor=StubTurnExecutor(),
        user_id=user.id,
        request_id="req-1",
        message="hello",
        conversation_id=None,
    )

    assert response.usage.input_tokens == 0
    assert response.usage.output_tokens == 0
    assert response.usage.cost_usd == 0.0


async def test_handle_chat_turn_raises_for_an_unknown_conversation_id(
    session: AsyncSession, user: User
) -> None:
    import pytest
    from sunil.core.conversations.gateway import UnknownConversationError

    trace = NullTraceContext(request_id="req-1")

    with pytest.raises(UnknownConversationError):
        await handle_chat_turn(
            session,
            trace,
            executor=StubTurnExecutor(),
            user_id=user.id,
            request_id="req-1",
            message="hello",
            conversation_id="does-not-exist",
        )
