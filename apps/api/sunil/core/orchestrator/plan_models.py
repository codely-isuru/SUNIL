"""The plan models — layer 3 (`Plan`, Pydantic) and layer 5 (`ValidatedPlan`) of
the plan-validation pipeline (ADR-004 + Amendment 1).

`Plan` re-validates everything a provider's constrained-decode grammar cannot
express: numeric bounds, cross-field structural rules (non-empty `steps`, unique
`steps[].id`) and — the load-bearing one — **the plan-literal rule**.

**The plan-literal rule (C2 §2, THREAT_MODEL §5.1 control 2).** A step's `params`
must be literals. No `{{…}}`, no `${…}`, no `$steps[…]`, no `<step_…>`: a plan
may not template a later step's parameter out of an earlier step's output.
Without this rule, the value the permission engine decided on and the value the
approval's `args_hash` was computed over are both placeholders that something
else substitutes later — and the thing doing the substituting is untrusted tool
output (C1 §3). That is a direct path from a prompt-injected GitHub issue body to
a privileged call with attacker-chosen arguments, arriving *after* the human
approved a different-looking one. A multi-step data flow is not forbidden
forever; it requires its own ADR and its own binding rules, and it is not
something an implementer may add by loosening a validator.

`ValidatedPlan` is minted only by `plan_validator.validate_plan()`, which holds
`_VALIDATOR_TOKEN`. **That is not itself the security boundary** (ADR-004
Amendment 1 is explicit): annotations are erased at runtime and
`object.__new__(ValidatedPlan)` bypasses `__init__` entirely. It stops every
*accidental* construction, which is worth having; the actual enforcement is
`guards.require_validated_plan()`'s `isinstance` check on the execution path.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Module-private; `plan_validator.py` is the one module that imports it. That is
# a convention review can check, not the enforcement itself.
_VALIDATOR_TOKEN = object()

#: Reference/templating syntaxes a plan's params may not contain. Deliberately a
#: denylist of SYNTAX rather than a "no braces" rule: an owner must still be able
#: to ask for a literal `{"a": 1}` to be written somewhere.
_TEMPLATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\{\{"),  # {{ steps.x.output }} — mustache/jinja
    re.compile(r"\$\{"),  # ${step_1.result} — shell/JS
    re.compile(r"\$(steps?|outputs?|results?)\b", re.IGNORECASE),  # $steps[0].data
    re.compile(r"<\s*step[_\-.]", re.IGNORECASE),  # <step_1.output>
)

#: The literal sentinel a step with no tool carries. A step that does not call a
#: tool still emits the field explicitly — an omitted key is not the same
#: statement as "no tool", and constrained decode needs every property present.
NO_TOOL = "none"


class PlanStep(BaseModel):
    """One `steps[]` entry, exactly as the model may have emitted it — before the
    registry re-check."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    action: str = Field(min_length=1, max_length=64)
    tool: str = NO_TOOL
    operation: str = NO_TOOL
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def _params_must_be_literals(cls, value: dict[str, Any]) -> dict[str, Any]:
        """The plan-literal rule — see the module docstring for why this is a
        security control and not a style preference."""
        serialised = json.dumps(value, sort_keys=True, default=str)
        for pattern in _TEMPLATE_PATTERNS:
            match = pattern.search(serialised)
            if match is not None:
                raise ValueError(
                    "step params must be literal values: found the reference "
                    f"syntax {match.group(0)!r}. A param templated from an earlier "
                    "step's output is not the value the permission decision and "
                    "the approval binding were computed over (C2 §2)."
                )
        return value


class Plan(BaseModel):
    """Layer 3. The name `Plan` is what C2 contract test 2 imports; `PlanDraft`
    is kept as an alias below so M1-era call sites read the same."""

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(min_length=1, max_length=100)
    confidence: float
    privacy_level: str
    objective: str = Field(min_length=1, max_length=2000)
    # Optional because C2 §5's fixed plan omits it: a plan that names no project
    # is legal, and the unknown-project failure is decided at layer 4 against the
    # project registry, not by a missing key here.
    project_key: str | None = None
    agents: list[str]
    tools: list[str] = Field(default_factory=list)
    steps: list[PlanStep]

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_interval(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0 inclusive")
        return value

    @field_validator("agents")
    @classmethod
    def _at_least_one_agent(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("a plan must name at least one agent to run it")
        return value

    @field_validator("steps")
    @classmethod
    def _steps_non_empty_with_unique_ids(cls, value: list[PlanStep]) -> list[PlanStep]:
        if not value:
            raise ValueError("steps must not be empty")
        ids = [step.id for step in value]
        if len(ids) != len(set(ids)):
            raise ValueError("steps[].id must be unique")
        return value


#: M1 called layer 3 `PlanDraft`; V2's contract suite imports `Plan`. One class,
#: both names, so neither vocabulary drifts into a second model.
PlanDraft = Plan


class ValidatedPlanStep:
    """The layer-5 counterpart of `PlanStep`, after layer 4 confirmed the
    tool/operation/grant triple is real. Immutable: `__slots__`, no setattr
    path, so nothing between validation and execution can rewrite a param."""

    __slots__ = ("id", "action", "tool", "operation", "params")

    def __init__(
        self,
        *,
        id: str,  # noqa: A002 - mirrors the wire field name
        action: str,
        tool: str,
        operation: str,
        params: dict[str, Any],
    ) -> None:
        self.id = id
        self.action = action
        self.tool = tool
        self.operation = operation
        self.params = params

    @property
    def is_tool_call(self) -> bool:
        return self.tool != NO_TOOL

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ValidatedPlanStep(id={self.id!r}, action={self.action!r}, "
            f"tool={self.tool!r}, operation={self.operation!r})"
        )


class ValidatedPlan:
    """Minted only by `plan_validator.validate_plan()` (layer 5).

    `raw` carries the original draft as a plain dict, which is what the `plans`
    table persists: a rejected *or* accepted plan is evidence, never a lost log
    line. It is scrubbed at the insert site (`turn.py`), because a draft is model
    output and model output can contain whatever was pasted into the prompt.
    """

    __slots__ = ("intent", "objective", "project_key", "agents", "tools", "steps", "plan_id", "raw")

    def __init__(
        self,
        *,
        _token: object,
        intent: str,
        objective: str,
        agents: list[str],
        steps: list[ValidatedPlanStep],
        plan_id: str,
        raw: dict[str, Any],
        project_key: str | None = None,
        tools: list[str] | None = None,
    ) -> None:
        if _token is not _VALIDATOR_TOKEN:
            raise TypeError(
                "ValidatedPlan may only be constructed by plan_validator.validate_plan()"
            )
        self.intent = intent
        self.objective = objective
        self.project_key = project_key
        self.agents = agents
        self.tools = tools or []
        self.steps = steps
        self.plan_id = plan_id
        self.raw = raw

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ValidatedPlan(plan_id={self.plan_id!r}, intent={self.intent!r}, "
            f"agents={self.agents!r}, steps={len(self.steps)})"
        )
