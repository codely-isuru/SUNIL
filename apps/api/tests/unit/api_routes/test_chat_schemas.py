"""The chat envelope's Pydantic schemas (T11a) — `docs/M1_BUILD_PLAN.md`
§6, the frozen contract. Field names here are load-bearing: the frontend
and QA are already building against this exact shape.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sunil.api.schemas import (
    ChatFailure,
    ChatRequest,
    ChatResponse,
    ChatTaskOut,
    ChatUsage,
    MessageOut,
    ProjectSummary,
    TraceEntryOut,
)


def test_chat_request_accepts_a_message_and_null_conversation_id() -> None:
    request = ChatRequest(message="Check on Sample Project.", conversation_id=None)

    assert request.message == "Check on Sample Project."
    assert request.conversation_id is None


def test_chat_request_rejects_an_empty_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="", conversation_id=None)


def test_chat_request_rejects_a_message_over_8000_characters() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(message="x" * 8001, conversation_id=None)


def test_chat_request_accepts_exactly_8000_characters() -> None:
    request = ChatRequest(message="x" * 8000, conversation_id=None)

    assert len(request.message) == 8000


def test_chat_response_serialises_the_success_shape() -> None:
    response = ChatResponse(
        request_id="req-1",
        conversation_id="conv-1",
        outcome="ok",
        message=MessageOut(
            id="msg-1", role="assistant", content="All quiet.", created_at="2026-08-17T00:00:00Z"
        ),
        task=ChatTaskOut(id="task-1", status="completed", assigned_agent="project_manager"),
        failure=None,
        trace=[TraceEntryOut(stage="message_received", offset_ms=0, detail=None)],
        usage=ChatUsage(input_tokens=100, output_tokens=50, cost_usd=0.002),
    )

    dumped = response.model_dump()
    assert dumped["outcome"] == "ok"
    assert dumped["message"]["role"] == "assistant"
    assert dumped["task"]["assigned_agent"] == "project_manager"
    assert dumped["failure"] is None
    assert dumped["usage"]["cost_usd"] == 0.002


def test_chat_response_serialises_the_failure_shape_with_null_message_and_task() -> None:
    response = ChatResponse(
        request_id="req-1",
        conversation_id="conv-1",
        outcome="failed",
        message=None,
        task=None,
        failure=ChatFailure(kind="plan_rejected", known_projects=None),
        trace=[],
        usage=ChatUsage(input_tokens=0, output_tokens=0, cost_usd=0.0),
    )

    dumped = response.model_dump()
    assert dumped["message"] is None
    assert dumped["task"] is None
    assert dumped["failure"]["kind"] == "plan_rejected"
    assert dumped["failure"]["known_projects"] is None


def test_chat_failure_carries_known_projects_for_unknown_project() -> None:
    failure = ChatFailure(
        kind="unknown_project",
        known_projects=[ProjectSummary(key="sample_project", display_name="Sample Project")],
    )

    assert failure.known_projects[0].key == "sample_project"


def test_chat_failure_kind_is_restricted_to_the_four_documented_values() -> None:
    for kind in ("provider_error", "tool_failed", "plan_rejected", "unknown_project"):
        ChatFailure(kind=kind, known_projects=None)

    with pytest.raises(ValidationError):
        ChatFailure(kind="cancelled", known_projects=None)
