"""`sunil.core.orchestrator.guards` — ADR-004 Amendment 1's runtime
enforcement. Guard site 1 (`execute_plan`) is T9's own; guard sites 2 and
3 (T10's agent runner, T8's `ToolManager.execute()`) are proven by T19's
security tests once those modules exist (`M1_BUILD_PLAN.md` §5 T19).
"""

from __future__ import annotations

import dataclasses

import pytest
from sunil.core.orchestrator.guards import (
    ExecutionMetadata,
    InvalidPlanExecution,
    execute_plan,
    require_validated_plan,
)
from sunil.core.orchestrator.plan_models import PlanDraft, ValidatedPlan
from sunil.core.orchestrator.plan_validator import validate_plan
from sunil.core.registry.loader import Registries


def test_execute_plan_rejects_a_dict() -> None:
    """The named ADR-004 §6.3 test: `InvalidPlanExecution`, and — because
    this raises before returning anything — no code that could construct
    a `tool_calls` row is ever reached from this call. That is what makes
    "no DB writes" true by construction rather than by convention: there
    is no `plan` value downstream of this exception."""
    with pytest.raises(InvalidPlanExecution):
        execute_plan({"intent": "project_status_review"})


def test_execute_plan_rejects_none() -> None:
    with pytest.raises(InvalidPlanExecution):
        execute_plan(None)


def test_execute_plan_rejects_a_plan_draft_that_was_never_validated() -> None:
    """A `PlanDraft` is a legitimate object in this codebase -- it is just
    not a `ValidatedPlan`, and the guard must not treat "looks plan-shaped"
    as "was validated"."""
    draft = PlanDraft(
        intent="project_status_review",
        confidence=0.9,
        privacy_level="internal",
        objective="x",
        project_key="__unknown__",
        agents=[],
        tools=[],
        steps=[{"id": "s1", "action": "resolve_project", "tool": "none"}],
    )

    with pytest.raises(InvalidPlanExecution):
        execute_plan(draft)


def test_execute_plan_accepts_a_genuine_validated_plan(
    registries: Registries, valid_plan: dict
) -> None:
    plan = validate_plan(valid_plan, registries)

    result = execute_plan(plan)

    assert result is plan


def test_require_validated_plan_is_the_same_function_execute_plan_calls(
    registries: Registries, valid_plan: dict
) -> None:
    """Documents that guard site 1 is a pass-through, not a second
    implementation -- one function, checked at every call site, exactly
    as ADR-004 Amendment 1 specifies."""
    plan = validate_plan(valid_plan, registries)

    assert require_validated_plan(plan) is plan


def test_forged_validated_plan_still_passes_the_isinstance_guard() -> None:
    """**The deliberate violation, proven and kept as a permanent
    regression test** (memory Principles: "prove fences, don't trust
    them"). `object.__new__` bypasses `ValidatedPlan.__init__` and its
    token check entirely -- Amendment 1's whole reason for existing --
    so a forged instance DOES pass `require_validated_plan()`. This is
    not a bug to fix: it is the documented residual risk that is why
    Amendment 1 additionally requires `ExecutionMetadata`, minted only by
    the orchestrator from a genuine validated plan and a real `Task`, so
    even a forged `ValidatedPlan` cannot produce a legitimate tool call
    without also forging execution metadata the agent has no path to
    construct."""
    forged = object.__new__(ValidatedPlan)

    # No exception -- this is the proof, not a mistake.
    accepted = require_validated_plan(forged)

    assert accepted is forged


def test_execution_metadata_is_frozen() -> None:
    """Privilege travels on this value; it must not be mutable after
    minting (Amendment 1 point 3)."""
    meta = ExecutionMetadata(
        validated_plan_id="plan-1", request_id="req-1", task_id="task-1", agent_id="project_manager"
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.agent_id = "attacker_agent"  # type: ignore[misc]


def test_execution_metadata_requires_all_four_fields() -> None:
    with pytest.raises(TypeError):
        ExecutionMetadata(validated_plan_id="plan-1", request_id="req-1")  # type: ignore[call-arg]
