"""`sunil.core.orchestrator.plan_models` — layers 3 and 5 (§6.1, ADR-004
Amendment 1)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from sunil.core.orchestrator.plan_models import PlanDraft, ValidatedPlan, ValidatedPlanStep


def test_plan_draft_rejects_an_out_of_range_confidence() -> None:
    """The one thing `output_config` cannot express (§4.3) and layer 3
    exists specifically to catch."""
    with pytest.raises(ValidationError):
        PlanDraft(
            intent="project_status_review",
            confidence=1.5,
            privacy_level="internal",
            objective="x",
            project_key="__unknown__",
            agents=[],
            tools=[],
            steps=[{"id": "s1", "action": "resolve_project", "tool": "none"}],
        )


def test_plan_draft_rejects_empty_steps() -> None:
    with pytest.raises(ValidationError):
        PlanDraft(
            intent="project_status_review",
            confidence=0.5,
            privacy_level="internal",
            objective="x",
            project_key="__unknown__",
            agents=[],
            tools=[],
            steps=[],
        )


def test_plan_draft_rejects_duplicate_step_ids() -> None:
    with pytest.raises(ValidationError):
        PlanDraft(
            intent="project_status_review",
            confidence=0.5,
            privacy_level="internal",
            objective="x",
            project_key="__unknown__",
            agents=[],
            tools=[],
            steps=[
                {"id": "s1", "action": "resolve_project", "tool": "none"},
                {"id": "s1", "action": "summarise_activity", "tool": "none"},
            ],
        )


def test_plan_draft_rejects_an_unexpected_field() -> None:
    """`extra="forbid"` — the model does not silently ignore a field the
    schema builder never emitted."""
    with pytest.raises(ValidationError):
        PlanDraft(
            intent="project_status_review",
            confidence=0.5,
            privacy_level="internal",
            objective="x",
            project_key="__unknown__",
            agents=[],
            tools=[],
            steps=[{"id": "s1", "action": "resolve_project", "tool": "none"}],
            unexpected_field="should not be accepted",
        )


def test_validated_plan_cannot_be_constructed_directly() -> None:
    """The named ADR-004 §6.3 test. Calling `ValidatedPlan(...)` from
    outside `plan_validator.validate_plan()` — i.e. without the
    module-private token — must raise `TypeError`, proving the
    *accidental*-construction fence (Amendment 1: this is not claimed to
    stop a deliberate bypass; see `test_validated_plan_construction_can_
    still_be_forged_by_a_deliberate_bypass` below and `guards.py` for
    what actually is the enforcement)."""
    with pytest.raises(TypeError):
        ValidatedPlan(
            _token=object(),  # NOT the real _VALIDATOR_TOKEN
            intent="project_status_review",
            objective="x",
            project_key="__unknown__",
            agents=[],
            tools=[],
            steps=[],
            plan_id="fake-plan-id",
            raw={},
        )


def test_validated_plan_construction_can_still_be_forged_by_a_deliberate_bypass() -> None:
    """**Prove the fence rather than trust it (memory L-002/Principles).**
    ADR-004 Amendment 1 withdrew "unforgeable" as a claim precisely
    because this is possible: `object.__new__` skips `__init__` and its
    token check entirely, producing a `ValidatedPlan`-typed instance that
    never touched `validate_plan()`. This test is the deliberate
    violation, written down and asserted TRUE — the opposite of every
    other test in this file — specifically so nobody "fixes" it by
    reintroducing the false claim. The actual control is
    `guards.require_validated_plan()`'s `isinstance()` check, which this
    forged object *would* pass (it IS a `ValidatedPlan` instance) —
    which is exactly why Amendment 1 additionally requires
    `ExecutionMetadata` and three call-site guards rather than relying on
    the type alone. See `test_guards.py` for the guard proof."""
    forged = object.__new__(ValidatedPlan)  # bypasses __init__ entirely
    forged.plan_id = "forged-with-no-validation-whatsoever"

    assert isinstance(forged, ValidatedPlan)  # the type check alone would accept this
    # Nothing below this line is a "fix" for the above -- it is the
    # documented, accepted shape of the residual risk Amendment 1 records.


def test_validated_plan_step_holds_its_fields() -> None:
    step = ValidatedPlanStep(id="s1", action="list_recent_activity", tool="github")

    assert step.id == "s1"
    assert step.action == "list_recent_activity"
    assert step.tool == "github"
