"""The runtime execution guard and trusted execution metadata (ADR-004
Amendment 1).

This module is the actual enforcement. `plan_models.ValidatedPlan`'s constructor
token only stops *accidental* construction: annotations are erased at runtime,
and `object.__new__(ValidatedPlan)` skips `__init__` altogether.

`require_validated_plan()` is the first statement at three call sites:

1. `execute_plan()` below — entry to plan execution (the orchestrator);
2. the agent runner, before an agent is handed a plan;
3. the C1 Tool Manager, before any adapter is reached (Stream A's file — the
   guard is imported, not reimplemented).

`ExecutionMetadata` is why privilege travels on a *value* rather than on a type:
the orchestrator mints it from a `ValidatedPlan` and a task, an agent cannot
construct one, and it is what lands on the `tool_calls` row so an executed call
is traceable to the exact plan that authorised it — without inference.
"""

from __future__ import annotations

from dataclasses import dataclass

from sunil.core.orchestrator.plan_models import ValidatedPlan


class InvalidPlanExecution(Exception):
    """The execution path was reached by something other than a genuine
    `ValidatedPlan`: a raw dict, a `Plan` draft, `None`, a plain object with the
    right attribute names, or a `ValidatedPlan`-shaped instance produced by
    `object.__new__` to dodge the constructor's token check."""


def require_validated_plan(plan: object) -> ValidatedPlan:
    """The one guard function. `isinstance` against the concrete class is a
    runtime check, not an erased annotation — this is what actually holds."""
    if not isinstance(plan, ValidatedPlan):
        raise InvalidPlanExecution(
            f"execution requires a ValidatedPlan, received {type(plan).__name__}"
        )
    return plan


def execute_plan(plan: object) -> ValidatedPlan:
    """Guard site 1: the very first statement of plan execution.

    Deliberately a thin pass-through and nothing else. Widening the scope of the
    one function every privileged path calls first would grow exactly the
    surface it exists to keep small.
    """
    return require_validated_plan(plan)


@dataclass(frozen=True)
class ExecutionMetadata:
    """Minted by the orchestrator only; required by the Tool Manager; written
    onto every `tool_calls` row."""

    validated_plan_id: str
    request_id: str
    task_id: str
    agent_id: str
