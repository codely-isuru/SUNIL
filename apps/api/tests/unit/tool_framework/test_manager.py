"""`sunil.core.tool_framework.manager.ToolManager` — the privileged gate
(`ARCHITECTURE_V1.md` §9.3, ADR-004 Amendment 1 guard site 3, ET-4, ET-7).
"""

from __future__ import annotations

import dataclasses

import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sunil.core.orchestrator.guards import ExecutionMetadata, InvalidPlanExecution
from sunil.core.orchestrator.plan_models import ValidatedPlan
from sunil.core.permissions.engine import Decision
from sunil.core.registry.loader import Registries
from sunil.core.registry.permissions import PermissionRegistry
from sunil.core.tool_framework.base import ToolOperation, ToolResult
from sunil.core.tool_framework.manager import ToolManager
from sunil.core.trace.context import NullTraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.models import ToolCall

# Deliberately no cross-file `from conftest import ...` here — a sibling
# test package (`tests/unit/registry/`) also defines a `conftest.py`, and
# without `__init__.py` packages, a bare `import conftest` risks resolving
# to whichever one pytest happened to cache first in this process
# (the same lesson T9's own conftest applied). Every fixture this file
# needs comes from this directory's `conftest.py` through pytest's normal
# fixture injection instead.


class _FakeParams(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_key: str


class _FakeGithubAdapter:
    """A fake adapter matching `ToolAdapter`'s shape, standing in for the
    real `GitHubAdapter` so these tests exercise the Tool Manager's own
    logic without a real HTTP layer."""

    name = "github"

    def __init__(self, handler_result: ToolResult | Exception | None = None) -> None:
        self._handler_result = handler_result or ToolResult(
            ok=True,
            data={"commits": [], "pull_requests": [], "issues": []},
            error_kind=None,
            error_message=None,
        )
        self.calls: list[_FakeParams] = []
        self.operations: dict[str, ToolOperation] = {
            "list_recent_activity": ToolOperation(
                name="list_recent_activity",
                params_model=_FakeParams,
                read_only=True,
                timeout_s=1.0,
                handler=self._handle,
            )
        }

    async def _handle(self, params: _FakeParams) -> ToolResult:
        self.calls.append(params)
        if isinstance(self._handler_result, Exception):
            raise self._handler_result
        return self._handler_result


async def _tool_call_rows(sessionmaker: async_sessionmaker[AsyncSession]) -> list[ToolCall]:
    async with sessionmaker() as session:
        result = await session.execute(select(ToolCall))
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Guard site 3 (ADR-004 Amendment 1) — proven first, before anything else.
# ---------------------------------------------------------------------------


async def test_execute_rejects_a_plan_that_is_not_a_validated_plan(
    execution_metadata: ExecutionMetadata,
) -> None:
    manager = ToolManager()

    with pytest.raises(InvalidPlanExecution):
        await manager.execute(
            plan={"not": "a ValidatedPlan"},
            tool="github",
            operation="list_recent_activity",
            params={"project_key": "x"},
            meta=execution_metadata,
        )


async def test_execute_rejects_a_forged_validated_plan_with_no_execution_metadata(
    validated_plan: ValidatedPlan,
) -> None:
    """The residual-risk case from T9's own deliberate-violation proof:
    `object.__new__(ValidatedPlan)` passes `isinstance`, so the guard that
    actually stops it here is the `ExecutionMetadata` check, not the type
    check alone."""
    manager = ToolManager()
    forged = object.__new__(ValidatedPlan)

    with pytest.raises(InvalidPlanExecution):
        await manager.execute(
            plan=forged,
            tool="github",
            operation="list_recent_activity",
            params={"project_key": "x"},
            meta=None,
        )


async def test_execute_rejects_metadata_missing_a_required_field(
    validated_plan: ValidatedPlan,
) -> None:
    incomplete = ExecutionMetadata(
        validated_plan_id="", request_id="r", task_id="t", agent_id="project_manager"
    )
    manager = ToolManager()

    with pytest.raises(InvalidPlanExecution):
        await manager.execute(
            plan=validated_plan,
            tool="github",
            operation="list_recent_activity",
            params={"project_key": "x"},
            meta=incomplete,
        )


async def test_a_bare_tool_manager_proves_the_guard_without_a_database(
    validated_plan: ValidatedPlan, execution_metadata: ExecutionMetadata
) -> None:
    """`ToolManager()` with no registries/sessionmaker at all must still
    raise a clear, named error once the guard passes — never an
    `AttributeError` from touching `None` internals."""
    manager = ToolManager()

    with pytest.raises(RuntimeError, match="registries.*sessionmaker"):
        await manager.execute(
            plan=validated_plan,
            tool="github",
            operation="list_recent_activity",
            params={"project_key": "x"},
            meta=execution_metadata,
        )


# ---------------------------------------------------------------------------
# ET-4 — the success path: exactly one ToolCall row, decision ALLOW.
# ---------------------------------------------------------------------------


async def test_successful_call_writes_exactly_one_allow_tool_call_row(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    adapter = _FakeGithubAdapter(
        ToolResult(
            ok=True,
            data={"commits": [], "pull_requests": [], "issues": []},
            error_kind=None,
            error_message=None,
        )
    )
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )
    trace = NullTraceContext(request_id="req-1")

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
        trace=trace,
    )

    assert result.ok is True
    assert adapter.calls, "the adapter's handler was never invoked"

    rows = await _tool_call_rows(sessionmaker)
    assert len(rows) == 1, f"expected exactly one tool_calls row (ET-4), got {len(rows)}"
    row = rows[0]
    assert row.permission_decision == Decision.ALLOW.value
    assert row.status == "ok"
    assert row.validated_plan_id == validated_plan.plan_id
    assert row.request_id == "req-1"
    assert row.task_id == "task-1"
    assert row.agent_id == "project_manager"

    stages = [stage for stage, _summary, _detail, _task in trace.emitted]
    assert TraceStage.PERMISSION_DECISION in stages
    assert TraceStage.TOOL_RESULT in stages


# ---------------------------------------------------------------------------
# Steps 1-3 — resolution / grant / parameter failures. Zero adapter calls.
# ---------------------------------------------------------------------------


async def test_unknown_tool_is_recorded_as_deny_not_executed_with_no_adapter_call(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    manager = ToolManager(adapters={}, registries=registries, sessionmaker=sessionmaker)

    result = await manager.execute(
        plan=validated_plan,
        tool="not_a_real_tool",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
    )

    assert result.ok is False
    assert result.error_kind == "unknown_operation"
    rows = await _tool_call_rows(sessionmaker)
    assert len(rows) == 1
    assert rows[0].status == "not_executed"
    assert rows[0].permission_decision == Decision.DENY.value


async def test_unknown_operation_on_a_known_tool_is_recorded_not_executed(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    adapter = _FakeGithubAdapter()
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="delete_repo",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
    )

    assert result.ok is False
    assert not adapter.calls
    rows = await _tool_call_rows(sessionmaker)
    assert rows[0].status == "not_executed"


async def test_agent_not_granted_the_tool_in_agents_yaml_is_denied_before_the_adapter(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    """Step 2 — FR-082's own duplicate check, at the Tool Manager."""
    registries.agents.get("project_manager").tools["github"] = []  # revoke, in-memory
    adapter = _FakeGithubAdapter()
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
    )

    assert result.ok is False
    assert result.error_kind == "not_granted_to_agent"
    assert not adapter.calls
    rows = await _tool_call_rows(sessionmaker)
    assert rows[0].status == "not_executed"


async def test_unknown_agent_id_on_the_metadata_is_denied(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
) -> None:
    meta = ExecutionMetadata(
        validated_plan_id=validated_plan.plan_id,
        request_id="req-1",
        task_id="task-1",
        agent_id="an_agent_that_does_not_exist",
    )
    adapter = _FakeGithubAdapter()
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=meta,
    )

    assert result.ok is False
    assert result.error_kind == "unknown_agent"
    assert not adapter.calls


async def test_invalid_parameters_are_denied_before_the_adapter_is_reached(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    """Step 3 — `extra="forbid"` — an attacker-shaped params dict carrying
    `owner`/`repo` is exactly what `test_repo_coordinates_never_come_from_
    a_plan` (T19) checks at the model level; this proves the Tool Manager
    actually enforces it at the call level too."""
    adapter = _FakeGithubAdapter()
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project", "owner": "attacker", "repo": "evil"},
        meta=execution_metadata,
    )

    assert result.ok is False
    assert result.error_kind == "invalid_params"
    assert not adapter.calls
    rows = await _tool_call_rows(sessionmaker)
    assert rows[0].status == "not_executed"


# ---------------------------------------------------------------------------
# Steps 4-5 — the permission decision itself (T7 composition).
# ---------------------------------------------------------------------------


async def test_permission_denied_stops_before_the_adapter(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    registries = dataclasses.replace(
        registries,
        permissions=PermissionRegistry(
            {"project_manager": {"github": {"list_recent_activity": "deny"}}}
        ),
    )
    adapter = _FakeGithubAdapter()
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
    )

    assert result.ok is False
    assert not adapter.calls
    rows = await _tool_call_rows(sessionmaker)
    assert rows[0].permission_decision == Decision.DENY.value
    assert rows[0].status == "not_executed"


async def test_no_grant_at_all_denies_by_default(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    """Mirrors T7's own default-deny test at the manager level: an empty
    `PermissionRegistry` — no entry at all, not even an explicit `deny` —
    must still stop the call."""
    registries = dataclasses.replace(registries, permissions=PermissionRegistry({}))
    adapter = _FakeGithubAdapter()
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
    )

    assert result.ok is False
    assert not adapter.calls
    rows = await _tool_call_rows(sessionmaker)
    assert rows[0].permission_decision == Decision.DENY.value
    assert rows[0].permission_reason == "no explicit grant"


# ---------------------------------------------------------------------------
# Steps 6-8 — adapter execution: timeout, exception, and normal error.
# ---------------------------------------------------------------------------


async def test_adapter_timeout_is_normalised_never_propagated(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    import asyncio

    class _SlowAdapter:
        name = "github"

        async def _handle(self, params: _FakeParams) -> ToolResult:
            await asyncio.sleep(10)
            return ToolResult(ok=True, data={}, error_kind=None, error_message=None)

        def __init__(self) -> None:
            self.operations = {
                "list_recent_activity": ToolOperation(
                    name="list_recent_activity",
                    params_model=_FakeParams,
                    read_only=True,
                    timeout_s=0.01,
                    handler=self._handle,
                )
            }

    manager = ToolManager(
        adapters={"github": _SlowAdapter()}, registries=registries, sessionmaker=sessionmaker
    )

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
    )

    assert result.ok is False
    assert result.error_kind == "timeout"
    rows = await _tool_call_rows(sessionmaker)
    assert rows[0].status == "error"


async def test_an_adapter_exception_never_propagates_out_of_execute(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    adapter = _FakeGithubAdapter(handler_result=RuntimeError("adapter blew up unexpectedly"))
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )

    result = await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
    )

    assert result.ok is False
    assert result.error_kind == "tool_error"
    rows = await _tool_call_rows(sessionmaker)
    assert rows[0].status == "error"


# ---------------------------------------------------------------------------
# ADR-014 capture policy + ADR-006 redaction, applied to tool_calls rows.
# ---------------------------------------------------------------------------


async def test_capture_policy_none_nulls_the_stored_result(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sunil.core.tool_framework import manager as manager_module
    from sunil.db.capture import CaptureDecision, CapturePolicy, RetentionClass, Sensitivity

    monkeypatch.setattr(
        manager_module,
        "resolve_capture",
        lambda **_kwargs: CaptureDecision(
            capture_policy=CapturePolicy.NONE,
            sensitivity=Sensitivity.INTERNAL,
            retention_class=RetentionClass.STANDARD,
            training_eligible=False,
        ),
    )
    adapter = _FakeGithubAdapter(
        ToolResult(
            ok=True, data={"commits": ["should not be stored"]}, error_kind=None, error_message=None
        )
    )
    manager = ToolManager(
        adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
    )

    await manager.execute(
        plan=validated_plan,
        tool="github",
        operation="list_recent_activity",
        params={"project_key": "sample_project"},
        meta=execution_metadata,
    )

    rows = await _tool_call_rows(sessionmaker)
    assert rows[0].result is None, "capture_policy=none must null the stored result"
    assert rows[0].capture_policy == "none"


async def test_a_registered_secret_never_reaches_the_stored_parameters_or_result(
    registries: Registries,
    sessionmaker: async_sessionmaker[AsyncSession],
    validated_plan: ValidatedPlan,
    execution_metadata: ExecutionMetadata,
) -> None:
    from sunil import redaction

    secret_value = "fake-test-secret-needle-for-redaction-proof"
    redaction.register(secret_value, name="test_secret")
    try:
        adapter = _FakeGithubAdapter(
            ToolResult(
                ok=True, data={"leak": f"token={secret_value}"}, error_kind=None, error_message=None
            )
        )
        manager = ToolManager(
            adapters={"github": adapter}, registries=registries, sessionmaker=sessionmaker
        )

        await manager.execute(
            plan=validated_plan,
            tool="github",
            operation="list_recent_activity",
            params={"project_key": "sample_project"},
            meta=execution_metadata,
        )

        rows = await _tool_call_rows(sessionmaker)
        serialised = str(rows[0].parameters) + str(rows[0].result)
        assert secret_value not in serialised, "a registered secret survived into tool_calls"
    finally:
        redaction.reset_registry_for_tests()
