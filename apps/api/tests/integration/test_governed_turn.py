"""The governed turn, end to end, through the real app against the frozen fakes.

This is the lane's acceptance evidence and the shape of `ARCHITECTURE_V2.md`
§6's L-001 trace: owner session → validated plan → a tool call through the C1
seam's permission hook → analysis → the C5 envelope, with the twelve stages
durable in `audit_events`, plus the ASK_USER park that ends the turn honestly
with `outcome="parked"` and a C4 `ApprovalRef`.

Nothing is mocked that the architecture names as a seam: the provider is C2 §5's
`FakeProvider`, the tool is C1 §6.3's `FakeToolAdapter` behind
`FakePermissionHook`, the approvals service is C4 §6's `FakeApprovalsService`.
The one double is the Tool Manager itself (Stream A's file — see
`tool_manager_double.py` for why the spine must not write it).
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from sunil.core.trace.stages import ALL_STAGES_IN_ORDER
from sunil.db.models import AuditEvent, Message, Task, ToolCall

pytestmark = pytest.mark.anyio if False else []  # asyncio_mode=auto handles this

WEB_HEADERS = {"X-SUNIL-Client": "web", "Origin": "http://localhost:3001"}


# --------------------------------------------------------------------------- #
# The happy path — the full governed turn
# --------------------------------------------------------------------------- #
async def test_a_governed_turn_plans_calls_a_tool_and_answers(app_client) -> None:
    client, app = app_client

    response = await client.post(
        "/api/v1/chat",
        json={"message": "PLAN: write the demo item"},
        headers=WEB_HEADERS,
    )

    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["outcome"] == "ok"
    assert envelope["failure"] is None and envelope["approval"] is None
    assert envelope["message"]["role"] == "assistant"
    assert envelope["message"]["content"]
    assert envelope["task"]["status"] == "completed"
    assert envelope["task"]["assigned_agent"] == "project_manager"
    assert envelope["usage"]["input_tokens"] > 0
    assert envelope["conversation_id"]
    assert envelope["request_id"]


async def test_the_turn_writes_all_twelve_stages_in_order(app_client) -> None:
    """ROADMAP §28: the turn is reconstructable from `audit_events` alone."""
    client, app = app_client

    response = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )
    request_id = response.json()["request_id"]

    async with app.state.sessionmaker() as session:
        rows = list(
            (
                await session.execute(
                    select(AuditEvent)
                    .where(AuditEvent.request_id == request_id)
                    .order_by(AuditEvent.seq)
                )
            ).scalars()
        )

    assert [row.stage for row in rows] == [stage.value for stage in ALL_STAGES_IN_ORDER]
    assert [row.seq for row in rows] == list(range(1, 13))
    # The envelope's trace is the same spine, not a separate story.
    assert [entry["stage"] for entry in response.json()["trace"]] == [
        stage.value for stage in ALL_STAGES_IN_ORDER
    ]


async def test_the_tool_call_is_recorded_with_its_permission_decision(app_client) -> None:
    client, app = app_client

    response = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )
    request_id = response.json()["request_id"]

    async with app.state.sessionmaker() as session:
        call = (
            await session.execute(select(ToolCall).where(ToolCall.request_id == request_id))
        ).scalar_one()

    assert (call.tool, call.operation) == ("fake_tool", "write_item")
    assert call.permission_decision == "allow"
    assert call.outcome == "ok"
    assert call.adapter_kind == "native"
    assert call.args_hash and call.validated_plan_id
    assert call.finalised_at is not None  # two-phase audit closed


async def test_the_tool_actually_ran(app_client, adapter) -> None:
    """The proof the seam is wired to a real handler and not short-circuited."""
    client, _ = app_client

    await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )

    assert adapter.store == {"demo": "1"}


async def test_both_messages_are_persisted_but_only_the_assistants_is_returned(
    app_client,
) -> None:
    """C5 §1: the user's own message is persisted and never echoed back."""
    client, app = app_client

    response = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )

    async with app.state.sessionmaker() as session:
        rows = list((await session.execute(select(Message).order_by(Message.seq))).scalars())

    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].content == "PLAN: write the demo item"
    assert response.json()["message"]["content"] != rows[0].content


async def test_a_second_turn_continues_the_same_conversation(app_client) -> None:
    client, _ = app_client
    first = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )
    conversation_id = first.json()["conversation_id"]

    second = await client.post(
        "/api/v1/chat",
        json={"message": "PLAN: write the demo item", "conversation_id": conversation_id},
        headers=WEB_HEADERS,
    )

    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id
    assert second.json()["request_id"] != first.json()["request_id"]


# --------------------------------------------------------------------------- #
# The parked path — ADR-031 / L-001 legs 3 and 4
# --------------------------------------------------------------------------- #
async def test_an_ask_user_tool_parks_the_turn_with_an_approval_ref(
    app_client, permissions
) -> None:
    client, app = app_client
    permissions.grants.clear()
    permissions.grant("project_manager", "fake_tool", "write_item", "ask_user")

    response = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )

    assert response.status_code == 200, response.text
    envelope = response.json()
    assert envelope["outcome"] == "parked"
    assert envelope["message"] is None and envelope["failure"] is None
    assert envelope["approval"]["approval_id"]
    assert envelope["approval"]["expires_at"]
    assert "fake_tool.write_item" in envelope["approval"]["summary"]
    assert envelope["task"]["status"] == "parked"

    async with app.state.sessionmaker() as session:
        task = (await session.execute(select(Task))).scalar_one()
        call = (await session.execute(select(ToolCall))).scalar_one()
    assert task.status == "parked"
    assert call.permission_decision == "ask_user"
    assert call.error_kind == "approval_required"
    assert call.approval_id == envelope["approval"]["approval_id"]


async def test_a_parked_turn_persists_a_resumable_continuation(
    app_client, permissions, approvals
) -> None:
    """C4 §1's restart safety: the approval carries the plan cursor, so a
    continuation after a process restart knows where to resume."""
    client, _ = app_client
    permissions.grants.clear()
    permissions.grant("project_manager", "fake_tool", "write_item", "ask_user")

    response = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )

    approval_id = response.json()["approval"]["approval_id"]
    row = approvals.approvals[approval_id]
    # `continuation` is deliberately ABSENT from the `Approval` row: it never
    # leaves the service over HTTP (C4 §4), so the park material is asserted on
    # the retained `ParkRequest` instead — which is also the only place that can
    # show the manager copied the caller's `ParkContext` verbatim.
    park_request = approvals.parked[approval_id]

    assert row.status == "pending"
    assert park_request.continuation["cursor"] == 0
    assert park_request.continuation["plan"]["steps"]
    assert park_request.args_hash == row.args_hash


async def test_a_parked_turn_still_writes_the_whole_spine(app_client, permissions) -> None:
    """A park is not a hole in the audit record: the turn ends at
    `final_response`, and every stage before it is there."""
    client, app = app_client
    permissions.grants.clear()
    permissions.grant("project_manager", "fake_tool", "write_item", "ask_user")

    response = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )
    request_id = response.json()["request_id"]

    async with app.state.sessionmaker() as session:
        rows = list(
            (
                await session.execute(
                    select(AuditEvent)
                    .where(AuditEvent.request_id == request_id)
                    .order_by(AuditEvent.seq)
                )
            ).scalars()
        )

    assert [row.stage for row in rows] == [stage.value for stage in ALL_STAGES_IN_ORDER]
    assert rows[-1].detail["outcome"] == "parked"


# --------------------------------------------------------------------------- #
# Failure paths — visible, traced, and with nothing half-executed
# --------------------------------------------------------------------------- #
async def test_a_denied_tool_fails_the_turn_and_never_runs_the_tool(
    app_client, permissions, adapter
) -> None:
    client, _ = app_client
    permissions.grants.clear()  # default-deny is the fake's structure too

    response = await client.post(
        "/api/v1/chat", json={"message": "PLAN: write the demo item"}, headers=WEB_HEADERS
    )

    envelope = response.json()
    assert envelope["outcome"] == "failed"
    assert envelope["failure"]["kind"] == "tool_failed"
    assert envelope["message"] is None and envelope["approval"] is None
    assert adapter.store == {}


async def test_a_provider_failure_surfaces_as_provider_error(app_client) -> None:
    client, _ = app_client

    response = await client.post(
        "/api/v1/chat", json={"message": "FAIL:auth"}, headers=WEB_HEADERS
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "failed"
    assert response.json()["failure"]["kind"] == "provider_error"


async def test_a_rejected_plan_produces_zero_tool_calls(app_client) -> None:
    """The plan validator is the only path to a tool call: a plan that fails it
    must leave no `tool_calls` row at all."""
    client, app = app_client

    response = await client.post(
        "/api/v1/chat", json={"message": "make up a plan"}, headers=WEB_HEADERS
    )

    assert response.json()["outcome"] == "failed"
    assert response.json()["failure"]["kind"] == "plan_rejected"
    async with app.state.sessionmaker() as session:
        assert list((await session.execute(select(ToolCall))).scalars()) == []


async def test_usage_counts_every_provider_attempt_including_the_failed_one(
    app_client, provider
) -> None:
    """C5 §1 / M1's A-2 rule: `usage` sums every attempt, including failures."""
    client, _ = app_client

    response = await client.post(
        "/api/v1/chat", json={"message": "FAIL:invalid_output"}, headers=WEB_HEADERS
    )

    # The fake raises `invalid_output` once (counted usage), then succeeds.
    assert len(provider.calls) >= 2
    assert response.json()["usage"]["input_tokens"] >= 200
