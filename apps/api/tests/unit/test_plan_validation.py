"""Plan validation — the only path from model output to a privileged action.

ROADMAP §25 / §33.5 and C2 §2: free-form LLM text can only become action through
constrained decode → Pydantic → registry re-check → the C1 chokepoint. Each of
those layers gets tests here, and so does the **plan-literal rule** (C2 §2 /
THREAT_MODEL §5.1 control 2): a step's params may not template a value out of an
earlier step's output, because a validated literal that is later substituted is
not the value the approval was bound to.
"""

from __future__ import annotations

import pytest

from sunil.core.orchestrator.guards import (
    InvalidPlanExecution,
    execute_plan,
    require_validated_plan,
)
from sunil.core.orchestrator.plan_models import (
    Plan,
    PlanStep,
    ValidatedPlan,
)
from sunil.core.orchestrator.plan_schema import build_plan_schema
from sunil.core.orchestrator.plan_validator import (
    MAX_PLAN_ATTEMPTS,
    PlanRejected,
    plan_attempts_exhausted,
    validate_plan,
)
from tests.fakes.fake_provider import FIXED_PLAN
from tests.fakes.fake_tool_adapter import FakeToolAdapter

AGENTS = {"project_manager": {"tools": {"fake_tool": ["echo", "write_item"]}}}


@pytest.fixture
def catalogue():
    from sunil.core.orchestrator.plan_validator import ToolCatalogue

    return ToolCatalogue.from_adapters([FakeToolAdapter()])


# --------------------------------------------------------------------------- #
# Layer 3 — the Pydantic model
# --------------------------------------------------------------------------- #
def test_the_c2_fixed_plan_validates_against_the_real_plan_model() -> None:
    """C2 §5's fixed plan is what every stream's FakeProvider returns. If `Plan`
    cannot validate it, either the fake or the schema is wrong."""
    plan = Plan.model_validate(FIXED_PLAN)

    assert plan.steps[0].tool == "fake_tool"
    assert plan.steps[0].operation == "write_item"
    assert plan.steps[0].params == {"key": "demo", "value": "1"}


def test_an_unknown_top_level_field_is_rejected() -> None:
    """`extra="forbid"`: a field the schema builder did not anticipate is a
    plan we do not understand, not a plan with a bonus."""
    with pytest.raises(ValueError):
        Plan.model_validate({**FIXED_PLAN, "run_as_root": True})


def test_confidence_must_be_in_the_unit_interval() -> None:
    with pytest.raises(ValueError):
        Plan.model_validate({**FIXED_PLAN, "confidence": 1.7})


def test_steps_must_be_non_empty_with_unique_ids() -> None:
    with pytest.raises(ValueError, match="steps must not be empty"):
        Plan.model_validate({**FIXED_PLAN, "steps": []})

    duplicated = [FIXED_PLAN["steps"][0], FIXED_PLAN["steps"][0]]
    with pytest.raises(ValueError, match="unique"):
        Plan.model_validate({**FIXED_PLAN, "steps": duplicated})


# --------------------------------------------------------------------------- #
# The plan-literal rule (C2 §2) — params are literals, never references
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "params",
    [
        {"key": "{{steps.step_1.output.key}}", "value": "1"},
        {"key": "demo", "value": "${step_1.result}"},
        {"key": "demo", "value": "$steps[0].data"},
        {"key": "demo", "value": {"nested": "{{ anything }}"}},
        {"key": "demo", "value": ["fine", "<step_1.output>"]},
    ],
)
def test_a_templated_param_is_not_a_legal_plan(params: dict) -> None:
    """C2 §2's plan-literal rule. Templating later params from earlier tool
    output would make the validated value a promise rather than a fact: the
    permission decision and the approval's `args_hash` would both be computed
    over a string that is replaced before execution — which is precisely the
    path a prompt-injected tool result would use to steer a second call."""
    with pytest.raises(ValueError, match="literal"):
        PlanStep.model_validate(
            {
                "id": "step_1",
                "action": "tool_call",
                "tool": "fake_tool",
                "operation": "write_item",
                "params": params,
            }
        )


def test_a_literal_that_merely_contains_braces_is_still_legal() -> None:
    """The rule targets reference SYNTAX, not every brace: an owner asking to
    write `{"a": 1}` into a file must still be expressible."""
    step = PlanStep.model_validate(
        {
            "id": "step_1",
            "action": "tool_call",
            "tool": "fake_tool",
            "operation": "write_item",
            "params": {"key": "demo", "value": '{"a": 1}'},
        }
    )

    assert step.params["value"] == '{"a": 1}'


# --------------------------------------------------------------------------- #
# Layer 4 — the registry re-check
# --------------------------------------------------------------------------- #
def test_a_valid_plan_becomes_a_validated_plan(catalogue) -> None:
    validated = validate_plan(FIXED_PLAN, agents=AGENTS, catalogue=catalogue)

    assert isinstance(validated, ValidatedPlan)
    assert validated.steps[0].tool == "fake_tool"
    assert validated.plan_id
    assert validated.raw["intent"] == "fake_intent"


def test_an_unknown_agent_is_rejected(catalogue) -> None:
    with pytest.raises(PlanRejected) as err:
        validate_plan({**FIXED_PLAN, "agents": ["ghost"]}, agents=AGENTS, catalogue=catalogue)

    assert any("ghost" in error for error in err.value.errors)


def test_an_unknown_tool_or_operation_is_rejected(catalogue) -> None:
    """Deliberately redundant with layer 1's constrained decode: layer 1 is the
    provider's guarantee, layer 4 is ours, and ours still holds if a provider
    without constrained decoding is ever swapped in."""
    bad_tool = {**FIXED_PLAN, "steps": [{**FIXED_PLAN["steps"][0], "tool": "rm_rf"}]}
    bad_op = {**FIXED_PLAN, "steps": [{**FIXED_PLAN["steps"][0], "operation": "drop_table"}]}

    for draft in (bad_tool, bad_op):
        with pytest.raises(PlanRejected):
            validate_plan(draft, agents=AGENTS, catalogue=catalogue)


def test_a_tool_the_agent_is_not_configured_for_is_rejected(catalogue) -> None:
    """config/agents.yaml is the second gate: the tool exists, the operation
    exists, and this agent still may not reach it."""
    narrow = {"project_manager": {"tools": {"fake_tool": ["echo"]}}}

    with pytest.raises(PlanRejected, match="agents.yaml"):
        validate_plan(FIXED_PLAN, agents=narrow, catalogue=catalogue)


def test_rejection_reports_every_problem_not_just_the_first(catalogue) -> None:
    """The caller feeds these back as corrective context for the next bounded
    attempt; one error at a time would burn the attempt budget rediscovering
    the same plan's other faults."""
    draft = {
        **FIXED_PLAN,
        "agents": ["ghost"],
        "steps": [{**FIXED_PLAN["steps"][0], "tool": "rm_rf"}],
    }

    with pytest.raises(PlanRejected) as err:
        validate_plan(draft, agents=AGENTS, catalogue=catalogue)

    assert len(err.value.errors) >= 2


def test_plan_attempts_are_bounded() -> None:
    assert MAX_PLAN_ATTEMPTS == 3
    assert not plan_attempts_exhausted(1)
    assert plan_attempts_exhausted(3)


# --------------------------------------------------------------------------- #
# Layer 5 + the execution guard (ADR-004 Amendment 1)
# --------------------------------------------------------------------------- #
def test_a_validated_plan_cannot_be_constructed_by_hand() -> None:
    with pytest.raises(TypeError):
        ValidatedPlan(
            _token=object(),
            intent="x",
            objective="x",
            agents=[],
            steps=[],
            plan_id="p",
            raw={},
        )


@pytest.mark.parametrize("impostor", [None, {}, FIXED_PLAN, "a string", object()])
def test_the_execution_guard_rejects_anything_that_is_not_a_validated_plan(
    impostor: object,
) -> None:
    """The actual enforcement: `isinstance` against the concrete class, because
    a type annotation is erased at runtime and `object.__new__` bypasses the
    constructor's token check entirely."""
    with pytest.raises(InvalidPlanExecution):
        require_validated_plan(impostor)
    with pytest.raises(InvalidPlanExecution):
        execute_plan(impostor)


def test_a_plan_shaped_object_built_to_dodge_the_constructor_is_still_rejected() -> None:
    dodged = object.__new__(_PlanLookalike)

    with pytest.raises(InvalidPlanExecution):
        require_validated_plan(dodged)


class _PlanLookalike:
    """Right attribute names, wrong class — the shape is not the authority."""

    intent = "x"
    objective = "x"
    steps: list = []
    plan_id = "p"


# --------------------------------------------------------------------------- #
# Layer 1 — the JSON schema handed to the provider
# --------------------------------------------------------------------------- #
def test_the_plan_schema_whitelists_the_live_registries(catalogue) -> None:
    """Constrained decoding makes an unregistered agent/tool/operation an
    unreachable token sequence — the whitelist is part of the grammar, not a
    post-hoc filter."""
    schema = build_plan_schema(agents=AGENTS, catalogue=catalogue)

    step = schema["properties"]["steps"]["items"]
    assert schema["properties"]["agents"]["items"]["enum"] == ["project_manager"]
    assert "fake_tool" in step["properties"]["tool"]["enum"]
    assert "write_item" in step["properties"]["operation"]["enum"]
    assert schema["additionalProperties"] is False
    assert step["additionalProperties"] is False
    # Every property in `required` — OpenAI's strict structured-output mode
    # rejects a schema where a property is merely absent from `required`.
    assert set(step["required"]) == set(step["properties"])
