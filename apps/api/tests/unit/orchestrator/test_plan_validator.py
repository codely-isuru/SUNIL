"""`sunil.core.orchestrator.plan_validator` — layer 4 + minting layer 5
(§6.1, §6.2, ADR-004). Includes the three named ADR-004 §6.3 tests that
are wholly within T9's own ownership: `test_unknown_agent_in_plan_is_
rejected`, `test_malformed_llm_output_creates_zero_tool_calls` (ET-7) and
`test_three_failed_plans_return_plan_rejected_outcome` (FR-062).

The other three named §6.3 tests --
`test_run_agent_rejects_a_non_validated_plan`,
`test_tool_manager_requires_execution_metadata` and
`test_tool_call_row_carries_validated_plan_id` -- test T10's agent runner
and T8's Tool Manager, neither of which exists on this branch. They are
explicitly assigned to T19/Security in `M1_BUILD_PLAN.md`'s own T19
section ("the ADR-004 Amendment 1 guard tests"), to be written once
those modules land; this module supplies the `InvalidPlanExecution`
guard and `ExecutionMetadata` those tests will exercise.
"""

from __future__ import annotations

import copy

import pytest
from sunil.core.orchestrator.guards import execute_plan
from sunil.core.orchestrator.plan_models import ValidatedPlan
from sunil.core.orchestrator.plan_validator import (
    MAX_PLAN_ATTEMPTS,
    PlanRejected,
    plan_attempts_exhausted,
    validate_plan,
)
from sunil.core.registry.loader import Registries


def test_validate_plan_accepts_a_well_formed_plan_and_returns_a_validated_plan(
    registries: Registries, valid_plan: dict
) -> None:
    result = validate_plan(valid_plan, registries)

    assert isinstance(result, ValidatedPlan)
    assert result.project_key == "easy_clean_workforce"
    assert result.agents == ["project_manager"]
    assert [s.action for s in result.steps] == [
        "resolve_project",
        "list_recent_activity",
        "summarise_activity",
    ]
    # And the resulting plan passes the runtime guard -- the whole point
    # of the chain (guard site 1).
    assert execute_plan(result) is result


def test_unknown_agent_in_plan_is_rejected(registries: Registries, valid_plan: dict) -> None:
    """The named ADR-004 §6.3 test (FR-061)."""
    valid_plan["agents"] = ["an_agent_that_does_not_exist"]

    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(valid_plan, registries)

    assert any("an_agent_that_does_not_exist" in e for e in excinfo.value.errors)


def test_unknown_tool_in_plan_is_rejected(registries: Registries, valid_plan: dict) -> None:
    valid_plan["tools"] = ["a_tool_that_does_not_exist"]

    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(valid_plan, registries)

    assert any("a_tool_that_does_not_exist" in e for e in excinfo.value.errors)


def test_unknown_project_key_in_plan_is_rejected(registries: Registries, valid_plan: dict) -> None:
    """`__unknown__` is legal (that is ET-11's structural path); a project
    key that is neither registered nor the sentinel is not."""
    valid_plan["project_key"] = "a_project_that_does_not_exist"

    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(valid_plan, registries)

    assert any("a_project_that_does_not_exist" in e for e in excinfo.value.errors)


def test_unknown_project_sentinel_is_accepted(registries: Registries, valid_plan: dict) -> None:
    """The reserved `__unknown__` sentinel must NOT be rejected as an
    unknown project -- that would break ET-11's structural path."""
    valid_plan["project_key"] = "__unknown__"
    valid_plan["agents"] = []
    valid_plan["tools"] = []
    valid_plan["steps"] = [{"id": "s1", "action": "resolve_project", "tool": "none"}]

    result = validate_plan(valid_plan, registries)

    assert result.project_key == "__unknown__"


def test_step_naming_a_tool_operation_the_tool_does_not_expose_is_rejected(
    registries: Registries, valid_plan: dict
) -> None:
    valid_plan["steps"] = [
        {"id": "s1", "action": "delete_repo", "tool": "github"},
    ]

    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(valid_plan, registries)

    assert any("delete_repo" in e for e in excinfo.value.errors)


def test_step_for_an_agent_not_granted_the_operation_in_agents_yaml_is_rejected(
    registries: Registries, valid_plan: dict
) -> None:
    """Layer 4's own check, independent of layer 1's enums: the agent's
    `config/agents.yaml` tool grant list is a second gate the schema
    enum alone does not enforce."""
    registries.agents.get("project_manager").tools["github"] = []  # revoke the grant in-memory
    valid_plan["steps"] = [{"id": "s1", "action": "list_recent_activity", "tool": "github"}]
    valid_plan["agents"] = ["project_manager"]

    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(valid_plan, registries)

    assert any("not configured" in e for e in excinfo.value.errors)


def test_step_with_no_permissions_yaml_grant_is_rejected(
    registries: Registries, valid_plan: dict
) -> None:
    """This is the check ADR-004 layer 4 names explicitly: "the named
    agent is actually granted the named tools in config/permissions.yaml".
    An empty permission registry (mirroring T7's own default-deny test)
    must fail plan validation, not merely fail later at tool-call time."""
    from sunil.core.registry.permissions import PermissionRegistry

    registries = Registries(
        agents=registries.agents,
        permissions=PermissionRegistry({}),
        projects=registries.projects,
        models=registries.models,
        tools=registries.tools,
        capture=registries.capture,
    )

    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(valid_plan, registries)

    assert any("no config/permissions.yaml grant" in e for e in excinfo.value.errors)


def test_non_tool_step_with_an_unrecognised_action_is_rejected(
    registries: Registries, valid_plan: dict
) -> None:
    valid_plan["steps"] = [{"id": "s1", "action": "delete_everything", "tool": "none"}]

    with pytest.raises(PlanRejected):
        validate_plan(valid_plan, registries)


def test_every_problem_is_collected_not_just_the_first(
    registries: Registries, valid_plan: dict
) -> None:
    """ADR-004: "carrying every mismatch found, not just the first"."""
    valid_plan["agents"] = ["nonexistent_agent"]
    valid_plan["tools"] = ["nonexistent_tool"]

    with pytest.raises(PlanRejected) as excinfo:
        validate_plan(valid_plan, registries)

    assert any("nonexistent_agent" in e for e in excinfo.value.errors)
    assert any("nonexistent_tool" in e for e in excinfo.value.errors)


def test_malformed_llm_output_creates_zero_tool_calls(
    registries: Registries, valid_plan: dict
) -> None:
    """The named ADR-004 §6.3 test -- **ET-7**, proven at the unit level.

    T9 owns no database, so this cannot literally run
    `SELECT count(*) FROM tool_calls`; what it proves instead is the
    structural precondition that query's zero result depends on: a
    malformed/unvalidatable draft never produces a `ValidatedPlan`, and
    every object this function *does* produce (a `PlanRejected`
    exception) is rejected by the very next gate (`execute_plan`, guard
    site 1) if anyone tried to run it anyway. There is no value flowing
    out of this test that a tool call could ever be built from.
    """
    malformed = {"this": "is not a plan at all", "steps": "not even a list"}

    produced_plan = None
    try:
        produced_plan = validate_plan(malformed, registries)
    except PlanRejected:
        pass

    assert produced_plan is None, "a malformed draft must never yield a ValidatedPlan"

    # Reinforce the fence at the next gate too: even if some future bug
    # let a raw dict slip past validate_plan's own exception, guard site 1
    # still refuses it.
    from sunil.core.orchestrator.guards import InvalidPlanExecution

    with pytest.raises(InvalidPlanExecution):
        execute_plan(malformed)


def test_three_failed_plans_return_plan_rejected_outcome(
    registries: Registries, valid_plan: dict
) -> None:
    """The named ADR-004 §6.3 test (FR-062).

    T9 does not own the turn-level retry loop or the HTTP outcome
    (`turn.py` is T11b's build) -- what belongs here is the bounded-retry
    *contract* `plan_attempts_exhausted()` implements, and the proof that
    every one of the `MAX_PLAN_ATTEMPTS` (3, ADR-000 Q6) attempts, each
    given equally malformed input, produces zero `ValidatedPlan`
    instances -- so a turn built correctly on top of this has no
    `tool_calls` row to have written by the time it gives up.
    """
    malformed = copy.deepcopy(valid_plan)
    malformed["agents"] = ["an_agent_that_does_not_exist"]

    validated_plans = []
    attempt = 0
    while True:
        attempt += 1
        try:
            validated_plans.append(validate_plan(malformed, registries))
        except PlanRejected:
            pass
        if plan_attempts_exhausted(attempt):
            break

    assert attempt == MAX_PLAN_ATTEMPTS == 3
    assert validated_plans == [], "no attempt in the bounded retry may produce a ValidatedPlan"
    assert plan_attempts_exhausted(3) is True
    assert plan_attempts_exhausted(2) is False
