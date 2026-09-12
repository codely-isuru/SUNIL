"""Ruling R8: the integration double must match the real ToolManager on every
C1-observable field a consumer may branch on. The wave-2 defect existed because
the double asserted a park shape the real manager never had — this file makes
that drift a red test instead of a green lie."""

from tests.fakes.fake_tool_adapter import FakeToolAdapter
from tests.fakes.fake_hooks import FakePermissionHook, RecordingAuditHook
from tests.fakes.fake_approvals import FakeApprovalsService
from tests.integration.tool_manager_double import ToolManagerDouble
from sunil.core.tool_framework.base import ParkContext, TraceContext
from sunil.core.tool_framework.manager import ToolManager


async def _park_result(manager_cls):
    hook = FakePermissionHook()
    hook.grant("agent-1", "fake_tool", "write_item", "ask_user")
    approvals = FakeApprovalsService()
    manager = manager_cls([FakeToolAdapter()], hook, approvals, RecordingAuditHook())
    result = await manager.execute(
        "agent-1", "fake_tool", "write_item", {"key": "demo", "value": "v"},
        trace=TraceContext(request_id="req-1", task_id="task-1", conversation_id="conv-1"),
        park_context=ParkContext(
            continuation={"plan_id": "plan-1", "cursor": 0},
            summary="fake_tool.write_item requires approval",
        ),
    )
    return result, approvals


async def test_double_park_result_matches_the_real_manager() -> None:
    real, real_approvals = await _park_result(ToolManager)
    double, double_approvals = await _park_result(ToolManagerDouble)

    # Fields consumers branch on: identical values (duration_ms is measured,
    # error_message is prose — both contract-excluded from branching, §4).
    assert double.ok == real.ok
    assert double.data == real.data == None  # noqa: E711 - the frozen §2 rule, asserted literally
    assert double.error_kind == real.error_kind == "approval_required"
    assert double.meta.adapter_kind == real.meta.adapter_kind
    assert double.meta.server_id == real.meta.server_id

    # The approval ref: same SHAPE, and each links to a row its own store parked.
    for result, approvals in ((real, real_approvals), (double, double_approvals)):
        assert result.approval is not None
        assert result.approval.approval_id in approvals.parked
        row = approvals.approvals[result.approval.approval_id]
        assert result.approval.expires_at == row.expires_at
