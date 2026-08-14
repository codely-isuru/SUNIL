"""Layer 4 of ADR-004 — the registry re-check — and the single call site
that mints layer 5's `ValidatedPlan`.

`validate_plan()` independently confirms every agent, tool, action and
project in a draft plan exists **now** (deliberately redundant with
layer 1's schema enums — layer 1 is the provider's guarantee, layer 4 is
ours: it still holds if a provider without constrained decoding is ever
swapped in), and that the named agent is actually granted the named
tools in `config/permissions.yaml`. It raises `PlanRejected` — carrying
every problem found, not just the first — on any failure, and never
returns a partial result: there is no code path from this function to a
`ValidatedPlan` for a plan it has not fully accepted.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from sunil.core.orchestrator.plan_models import (
    _VALIDATOR_TOKEN,  # the one authorised import of this name
    PlanDraft,
    PlanStepDraft,
    ValidatedPlan,
    ValidatedPlanStep,
)
from sunil.core.orchestrator.plan_schema import NON_TOOL_ACTIONS
from sunil.core.registry import Registries
from sunil.core.registry.projects import UNKNOWN_PROJECT_KEY

# ADR-000 Q6: at most 3 logical plan attempts per turn. Repeated here
# (rather than only in `ARCHITECTURE_V1.md`) because this module is what
# enforces the bound the moment it is checked.
MAX_PLAN_ATTEMPTS = 3

_NO_TOOL_SENTINEL = "none"


class PlanRejected(Exception):
    """Raised when a draft plan fails layer 3 (Pydantic) or layer 4
    (registry re-check). Carries every error found so the caller
    (T11b's `turn.py`) can feed them back as corrective context for the
    next of the bounded 3 attempts, or — once `plan_attempts_exhausted()`
    is true — terminate the turn with outcome `plan_rejected` (FR-062),
    emitting stage 12 with **zero** `tool_calls` rows (ET-7).
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors: tuple[str, ...] = tuple(errors)
        super().__init__("; ".join(errors) or "plan rejected with no specific errors recorded")


def plan_attempts_exhausted(attempt: int) -> bool:
    """`attempt` is 1-indexed. True once the ADR-000 Q6 bounded-retry
    budget is spent and the turn must terminate with outcome
    `plan_rejected` rather than request another plan."""
    return attempt >= MAX_PLAN_ATTEMPTS


def _as_plan_draft(draft: dict[str, Any] | PlanDraft) -> PlanDraft:
    if isinstance(draft, PlanDraft):
        return draft
    try:
        return PlanDraft.model_validate(draft)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        raise PlanRejected(errors) from exc


def validate_plan(draft: dict[str, Any] | PlanDraft, registries: Registries) -> ValidatedPlan:
    """The layer-3 + layer-4 + layer-5 pipeline, in one call.

    Raises `PlanRejected` on the first fully-collected set of problems —
    never constructs a `ValidatedPlan` from a plan this function has not
    completely accepted. `TypeError` from `ValidatedPlan.__init__` is not
    reachable from here going wrong in the normal sense; it is reachable
    only by a caller that already holds `_VALIDATOR_TOKEN`, which is to
    say: only from within this function.
    """
    parsed = _as_plan_draft(draft)
    errors: list[str] = []

    if parsed.project_key != UNKNOWN_PROJECT_KEY and parsed.project_key not in registries.projects:
        errors.append(f"unknown project_key {parsed.project_key!r}")

    for agent_id in parsed.agents:
        if agent_id not in registries.agents:
            errors.append(f"unknown agent {agent_id!r}")

    for tool in parsed.tools:
        if tool not in registries.tools.tool_names():
            errors.append(f"unknown tool {tool!r}")

    validated_steps = _validate_steps(parsed, registries, errors)

    if errors:
        raise PlanRejected(errors)

    return ValidatedPlan(
        _token=_VALIDATOR_TOKEN,
        intent=parsed.intent,
        objective=parsed.objective,
        project_key=parsed.project_key,
        agents=list(parsed.agents),
        tools=list(parsed.tools),
        steps=validated_steps,
        plan_id=str(uuid4()),
        raw=parsed.model_dump(),
    )


def _validate_steps(
    parsed: PlanDraft, registries: Registries, errors: list[str]
) -> list[ValidatedPlanStep]:
    validated_steps: list[ValidatedPlanStep] = []

    for step in parsed.steps:
        if step.tool == _NO_TOOL_SENTINEL:
            _validate_non_tool_step(step, errors)
            validated_steps.append(
                ValidatedPlanStep(id=step.id, action=step.action, tool=_NO_TOOL_SENTINEL)
            )
            continue

        if not _validate_tool_step(step, parsed, registries, errors):
            continue

        validated_steps.append(ValidatedPlanStep(id=step.id, action=step.action, tool=step.tool))

    return validated_steps


def _validate_non_tool_step(step: PlanStepDraft, errors: list[str]) -> None:
    if step.action not in NON_TOOL_ACTIONS:
        errors.append(f"step {step.id!r}: action {step.action!r} is not a valid non-tool action")


def _validate_tool_step(
    step: PlanStepDraft, parsed: PlanDraft, registries: Registries, errors: list[str]
) -> bool:
    """Returns `True` iff the step is well-formed enough to include in the
    validated plan (errors may still have been appended for a permission
    gap, which rejects the whole plan without corrupting `validated_steps`
    with a step this function could not confirm exists)."""
    if step.tool not in registries.tools.tool_names():
        errors.append(f"step {step.id!r}: unknown tool {step.tool!r}")
        return False

    if not registries.tools.has_operation(step.tool, step.action):
        errors.append(f"step {step.id!r}: tool {step.tool!r} has no operation {step.action!r}")
        return False

    ok = True
    for agent_id in parsed.agents:
        if agent_id not in registries.agents:
            continue  # already recorded as an unknown-agent error above
        agent = registries.agents.get(agent_id)
        if step.action not in agent.tools.get(step.tool, []):
            errors.append(
                f"step {step.id!r}: agent {agent_id!r} is not configured for "
                f"{step.tool}.{step.action} in config/agents.yaml"
            )
            ok = False
        if registries.permissions.grant_for(agent_id, step.tool, step.action) is None:
            errors.append(
                f"step {step.id!r}: no config/permissions.yaml grant for "
                f"{agent_id}.{step.tool}.{step.action}"
            )
            ok = False

    return ok
