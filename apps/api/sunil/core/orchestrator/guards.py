"""ADR-004 Amendment 1 — the runtime execution guard and trusted
execution metadata. This module is the actual enforcement the design
needs; `plan_models.ValidatedPlan`'s constructor guard only stops
*accidental* construction (see that module's docstring).

`require_validated_plan()` is the first statement at **three** call
sites (`ARCHITECTURE_V1.md` §6.1):

1. `execute_plan()` below — guard site 1, owned by T9.
2. T10's agent runner (`core/agent_framework/runner.py`) — guard site 2.
3. T8's `ToolManager.execute()` (`core/tool_framework/manager.py`) —
   guard site 3.

One function, three call sites, three tests — T9 provides the function
and its own test (guard site 1); T19/Security provides
`test_run_agent_rejects_a_non_validated_plan` and
`test_tool_manager_requires_execution_metadata` once T10 and T8 exist
(`M1_BUILD_PLAN.md` §5 T19), because guard sites 2 and 3 live in modules
this task does not own.
"""

from __future__ import annotations

from dataclasses import dataclass

from sunil.core.orchestrator.plan_models import ValidatedPlan


class InvalidPlanExecution(Exception):
    """Raised by `require_validated_plan()` when the execution path is
    reached by anything other than a genuine `ValidatedPlan` — a raw
    `dict`, a `PlanDraft`, `None`, a plain object with the right
    attribute names, or a `ValidatedPlan`-shaped instance produced by
    `object.__new__` to dodge `__init__`'s token check."""


def require_validated_plan(plan: object) -> ValidatedPlan:
    """The one guard function, called at all three sites above.
    `isinstance()` is a runtime check against the concrete class, not an
    erased annotation — this is what Amendment 1 says actually holds."""
    if not isinstance(plan, ValidatedPlan):
        raise InvalidPlanExecution(
            f"execution requires a ValidatedPlan, received {type(plan).__name__}"
        )
    return plan


def execute_plan(plan: object) -> ValidatedPlan:
    """Guard site 1. The very first statement of plan execution: reject
    anything that is not a genuine `ValidatedPlan` before any downstream
    code — the agent runner (guard site 2), the Tool Manager (guard site
    3) — is ever reached. T11b's `turn.py` calls this (or an identical
    inline guard) as the entry point of stage 7 onward; the guard itself
    is what T9 is responsible for proving.

    Deliberately a thin pass-through and nothing else: `execute_plan`
    does not run the plan, only gates entry to whatever does. Widening
    its scope (validation, agent dispatch) after M1 would grow the
    attack surface of the one function every privileged path calls
    first.
    """
    return require_validated_plan(plan)


@dataclass(frozen=True)
class ExecutionMetadata:
    """Privilege travels on this value, not on `ValidatedPlan`'s type
    alone (Amendment 1 point 3). Minted only by the orchestrator from a
    `ValidatedPlan` and a `Task` — an agent cannot construct one itself —
    and required by `ToolManager.execute()` (T8), which writes all four
    fields onto the `tool_calls` row (`validated_plan_id`, `request_id`,
    `task_id`, `agent_id`) so every executed call is traceable to the
    exact plan that authorised it without inference.
    """

    validated_plan_id: str
    request_id: str
    task_id: str
    agent_id: str
