"""Layer 4 — the registry re-check — and the single call site that mints layer
5's `ValidatedPlan`.

`validate_plan()` independently confirms that every agent, tool and operation a
draft names exists **now**, and that the named agent is actually granted that
operation in `config/agents.yaml`. This is deliberately redundant with the
provider's constrained decode: layer 1 is the *provider's* guarantee, layer 4 is
ours, and ours still holds if a provider without constrained decoding is ever
swapped in (or if a gateway silently drops `response_format`).

It raises `PlanRejected` carrying **every** problem found — the caller feeds
them back as corrective context for the next of the bounded attempts, and one
error at a time would burn the attempt budget rediscovering the same faults.
There is no code path from this function to a `ValidatedPlan` for a plan it has
not fully accepted.

**Where the tool registry comes from.** `config/tools.yaml` is Stream A's file,
so this module does not read it. `ToolCatalogue` is built from the **C1 adapter
registry** the app already holds (`ToolAdapter.name` + `.operations`), which is
itself built from that config at boot — one source of truth, consulted through
the seam that owns it, rather than a second parser of someone else's file.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from pydantic import ValidationError

from sunil.core.orchestrator.plan_models import (
    NO_TOOL,
    _VALIDATOR_TOKEN,  # the one authorised import of this name
    Plan,
    PlanStep,
    ValidatedPlan,
    ValidatedPlanStep,
)
from sunil.db.base import new_uuid

#: At most three logical plan attempts per turn. Stated here because this module
#: is where the bound is checked.
MAX_PLAN_ATTEMPTS = 3


class _AdapterLike(Protocol):
    name: str
    operations: Mapping[str, Any]


class PlanRejected(Exception):
    """A draft failed layer 3 (Pydantic) or layer 4 (registry re-check).

    Carries every error found, so the turn can either re-ask with corrective
    context or — once the attempt budget is spent — terminate with
    `outcome="failed"`, `failure.kind="plan_rejected"` and **zero** `tool_calls`
    rows. A rejected plan must never execute partially.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors: tuple[str, ...] = tuple(errors)
        super().__init__("; ".join(errors) or "plan rejected with no specific errors recorded")


def plan_attempts_exhausted(attempt: int) -> bool:
    """`attempt` is 1-indexed."""
    return attempt >= MAX_PLAN_ATTEMPTS


@dataclass(frozen=True)
class ToolCatalogue:
    """What tools and operations exist, as far as the C1 adapter registry knows.

    A tool absent from here cannot be planned — and an adapter whose `start()`
    failed is absent from the registry entirely (C1's `ToolAdapterStartupError`
    rule: absent, never half-present), so a broken server cannot be planned
    against either.
    """

    operations_by_tool: Mapping[str, frozenset[str]]

    @classmethod
    def from_adapters(cls, adapters: Sequence[_AdapterLike]) -> ToolCatalogue:
        return cls(
            operations_by_tool={
                adapter.name: frozenset(adapter.operations) for adapter in adapters
            }
        )

    def has_tool(self, tool: str) -> bool:
        return tool in self.operations_by_tool

    def has_operation(self, tool: str, operation: str) -> bool:
        return operation in self.operations_by_tool.get(tool, frozenset())


def validate_plan(
    draft: dict[str, Any] | Plan,
    *,
    agents: Mapping[str, Any],
    catalogue: ToolCatalogue,
    projects: Mapping[str, Any] | None = None,
) -> ValidatedPlan:
    """The layer-3 + layer-4 + layer-5 pipeline, in one call.

    `agents` is the `config/agents.yaml` registry (`{agent_id: {tools: {tool:
    [operation, …]}}}`); `projects` is the optional project registry, checked
    only when the plan names a `project_key`.
    """
    parsed = _as_plan(draft)
    errors: list[str] = []

    if parsed.project_key is not None and projects is not None:
        if parsed.project_key not in projects:
            errors.append(f"unknown project_key {parsed.project_key!r}")

    for agent_id in parsed.agents:
        if agent_id not in agents:
            errors.append(f"unknown agent {agent_id!r}")

    for tool in parsed.tools:
        if not catalogue.has_tool(tool):
            errors.append(f"unknown tool {tool!r}")

    validated_steps = _validate_steps(parsed, agents, catalogue, errors)

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
        plan_id=new_uuid(),
        raw=parsed.model_dump(),
    )


def _as_plan(draft: dict[str, Any] | Plan) -> Plan:
    if isinstance(draft, Plan):
        return draft
    try:
        return Plan.model_validate(draft)
    except ValidationError as exc:
        raise PlanRejected(
            [f"{'.'.join(str(part) for part in e['loc'])}: {e['msg']}" for e in exc.errors()]
        ) from exc


def _validate_steps(
    parsed: Plan,
    agents: Mapping[str, Any],
    catalogue: ToolCatalogue,
    errors: list[str],
) -> list[ValidatedPlanStep]:
    validated: list[ValidatedPlanStep] = []

    for step in parsed.steps:
        if step.tool == NO_TOOL:
            validated.append(
                ValidatedPlanStep(
                    id=step.id,
                    action=step.action,
                    tool=NO_TOOL,
                    operation=NO_TOOL,
                    params=dict(step.params),
                )
            )
            continue

        if not _validate_tool_step(step, parsed, agents, catalogue, errors):
            continue

        validated.append(
            ValidatedPlanStep(
                id=step.id,
                action=step.action,
                tool=step.tool,
                operation=step.operation,
                params=dict(step.params),
            )
        )

    return validated


def _validate_tool_step(
    step: PlanStep,
    parsed: Plan,
    agents: Mapping[str, Any],
    catalogue: ToolCatalogue,
    errors: list[str],
) -> bool:
    """True iff the step is well-formed enough to appear in the validated plan.

    A grant gap still appends an error (so the whole plan is rejected) while
    returning True, so `validated_steps` never holds a step this function could
    not confirm exists.
    """
    if not catalogue.has_tool(step.tool):
        errors.append(f"step {step.id!r}: unknown tool {step.tool!r}")
        return False

    if not catalogue.has_operation(step.tool, step.operation):
        errors.append(
            f"step {step.id!r}: tool {step.tool!r} has no operation {step.operation!r}"
        )
        return False

    for agent_id in parsed.agents:
        agent = agents.get(agent_id)
        if agent is None:
            continue  # already recorded as an unknown-agent error
        granted = _agent_operations(agent, step.tool)
        if step.operation not in granted:
            errors.append(
                f"step {step.id!r}: agent {agent_id!r} is not configured for "
                f"{step.tool}.{step.operation} in config/agents.yaml"
            )

    return True


def _agent_operations(agent: Any, tool: str) -> frozenset[str]:
    """`agents.yaml` is a plain mapping when loaded and a small object when it
    comes from the registry loader; both are read here without either side
    having to know about the other."""
    tools = agent.get("tools", {}) if isinstance(agent, Mapping) else getattr(agent, "tools", {})
    return frozenset(tools.get(tool, ()))
