"""ADR-004 Amendment 1 — the runtime guards that replaced the withdrawn
"unforgeable" claim.

Amendment 1 withdrew "there is no expressible code path from raw LLM output to
a tool adapter" and replaced it with a claim the code can actually keep: a
ValidatedPlan is minted in exactly one place, and every privileged entry point
verifies at runtime that it received one, with trusted ExecutionMetadata
travelling alongside.

That replacement is only true if `require_validated_plan()` is genuinely
called at all three sites and if `isinstance` genuinely proves something. The
second condition is not free — see
test_validated_plan_is_a_concrete_class_not_a_protocol.

RED until T9 (guards), T10 (runner) and T8 (manager).
"""

from __future__ import annotations

import typing

import pytest
from conftest import require


def test_validated_plan_cannot_be_constructed_directly() -> None:
    """ADR-004 layer 5, and the mint-site claim of Amendment 1."""
    plan_models = require("sunil.core.orchestrator.plan_models", "T9 (plan validation + guards)")

    with pytest.raises(TypeError):
        plan_models.ValidatedPlan(steps=[], agent="project_manager", confidence=1.0)


def test_validated_plan_is_a_concrete_class_not_a_protocol() -> None:
    """The guard is `isinstance(obj, ValidatedPlan)`. If ValidatedPlan were a
    Protocol — and especially a @runtime_checkable one — that call would check
    only attribute *shape*, so any duck-typed object minted anywhere would pass
    and Amendment 1 enforcement would silently be worth nothing.

    T1 has already set the `@runtime_checkable Protocol` precedent in this
    codebase (sunil/core/trace/context.py), so this is a live risk, not a
    hypothetical one.
    """
    plan_models = require("sunil.core.orchestrator.plan_models", "T9")

    cls = plan_models.ValidatedPlan
    assert not issubclass(cls, typing.Protocol), (
        "ValidatedPlan is a Protocol — isinstance() then proves shape, not provenance, "
        "and the ADR-004 Amendment 1 guard is decorative"
    )
    assert not getattr(cls, "_is_runtime_protocol", False), (
        "ValidatedPlan is @runtime_checkable — any object with matching attributes passes the guard"
    )

    class LooksLikeOne:
        steps: list = []
        agent = "project_manager"
        confidence = 1.0

    assert not isinstance(LooksLikeOne(), cls), "a duck-typed object satisfied the guard"


def test_execute_plan_rejects_a_dict() -> None:
    """Guard site 1 (THREAT_MODEL section 11: test_execute_plan_rejects_a_dict)."""
    guards = require("sunil.core.orchestrator.guards", "T9")
    turn = require("sunil.core.orchestrator.turn", "T11b (orchestrator turn)")

    with pytest.raises(guards.InvalidPlanExecution):
        turn.execute_plan({"agent": "project_manager", "steps": [{"tool": "github"}]})


def test_run_agent_rejects_a_non_validated_plan() -> None:
    """Guard site 2 — the agent runner (M1_BUILD_PLAN.md section 5 T19)."""
    guards = require("sunil.core.orchestrator.guards", "T9")
    runner = require("sunil.core.agent_framework.runner", "T10 (agent framework)")

    with pytest.raises(guards.InvalidPlanExecution):
        runner.run_agent(agent_id="project_manager", plan={"not": "a ValidatedPlan"})


def test_tool_manager_requires_execution_metadata() -> None:
    """Guard site 3, step 0 of ARCHITECTURE_V1.md section 9.3: reject any call
    not carrying ExecutionMetadata whose validated_plan_id, request_id, task_id
    and agent_id are all present."""
    guards = require("sunil.core.orchestrator.guards", "T9")
    manager_mod = require("sunil.core.tool_framework.manager", "T8 (tool framework)")

    manager = manager_mod.ToolManager()

    with pytest.raises((guards.InvalidPlanExecution, TypeError)):
        manager.execute(
            tool="github", operation="list_recent_activity", params={"project_key": "x"}
        )

    partial = manager_mod.ExecutionMetadata if hasattr(manager_mod, "ExecutionMetadata") else None
    if partial is not None:
        with pytest.raises((guards.InvalidPlanExecution, TypeError, ValueError)):
            manager.execute(
                tool="github",
                operation="list_recent_activity",
                params={"project_key": "x"},
                meta=partial(validated_plan_id=None, request_id="r", task_id="t", agent_id="a"),
            )


def test_execution_metadata_is_frozen() -> None:
    """Amendment 1 point 3: "An agent cannot construct one". A mutable metadata
    object can be edited after minting, which is the same hole with extra steps."""
    guards = require("sunil.core.orchestrator.guards", "T9")

    meta = guards.ExecutionMetadata(
        validated_plan_id="p", request_id="r", task_id="t", agent_id="project_manager"
    )
    # frozen dataclass -> FrozenInstanceError; frozen pydantic model -> ValidationError
    with pytest.raises((AttributeError, TypeError, ValueError)):
        meta.agent_id = "someone_else"


def test_tool_call_row_carries_the_validated_plan_id() -> None:
    """Amendment 1 point 3 — the audit link. "Every executed tool call now
    names the plan that authorised it." Without this the guard is unfalsifiable
    after the fact."""
    require("sunil.db.models", "T2 (data layer)")
    models = __import__("sunil.db.models", fromlist=["ToolCall"])

    columns = {c.name for c in models.ToolCall.__table__.columns}
    for required in ("validated_plan_id", "request_id", "task_id", "agent_id"):
        assert required in columns, f"tool_calls has no `{required}` column: {sorted(columns)}"


def test_agent_context_exposes_no_session_no_client_and_no_secret() -> None:
    """NFR-007 and ARCHITECTURE_V1.md section 10.1: AgentContext exposes exactly
    call_tool, ask_model, memory, trace — no DB session, no HTTP client, no
    secrets. This is T-10 defence "by construction"."""
    base = require("sunil.core.agent_framework.base", "T10")

    allowed = {"call_tool", "ask_model", "memory", "trace"}
    public = {
        name for name in dir(base.AgentContext) if not name.startswith("_") and not name.isupper()
    }
    extra = public - allowed
    assert not extra, (
        f"AgentContext exposes more than the four granted capabilities: {sorted(extra)}"
    )


def test_empty_permission_config_denies_everything() -> None:
    """FR-120 / T-09. ARCHITECTURE_V1.md section 9.2: default-deny is
    *structural* — the missing-key branch returns DENY. M1_BUILD_PLAN.md T7:
    "it is what makes default-deny a fact rather than a description"."""
    engine = require("sunil.core.permissions.engine", "T7 (permission engine)")

    result = engine.decide(
        agent_id="project_manager", tool="github", operation="list_recent_activity"
    )
    with_empty_config = engine.decide_with(config={}, agent_id="a", tool="t", operation="o")
    assert with_empty_config.decision == engine.Decision.DENY
    assert with_empty_config.source == "default-deny"
    assert result is not None
