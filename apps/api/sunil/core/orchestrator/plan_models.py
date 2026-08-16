"""Layer 3 (`PlanDraft`, Pydantic) and layer 5 (`ValidatedPlan`) of
ADR-004, amended per Amendment 1.

`PlanDraft` re-validates everything the JSON Schema in `plan_schema.py`
cannot express under `output_config` (§4.3): numeric bounds
(`0.0 <= confidence <= 1.0`) and cross-field structural rules (non-empty
`steps`, unique `steps[].id`).

`ValidatedPlan` is minted only by `plan_validator.validate_plan()`, which
holds `_VALIDATOR_TOKEN` — the *one* authorised import site for that
name. **Amendment 1 is explicit that this is not itself the security
boundary**: type annotations are erased at runtime, and
`object.__new__(ValidatedPlan)` bypasses `__init__` (and therefore the
token check) entirely. The design still stops every *accidental*
construction, which is worth having, but the actual enforcement is
`guards.require_validated_plan()`'s `isinstance()` check on the
execution path — see `guards.py`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

# Module-private; never exported from `__init__.py` or `__all__`.
# `plan_validator.py` is the one module that imports this name — that is
# a convention `ruff`/review can check, not the enforcement itself
# (ADR-004 Amendment 1: "a module-private name is a naming convention...
# importable by any module that wants it").
_VALIDATOR_TOKEN = object()


class PlanStepDraft(BaseModel):
    """One `steps[]` entry, exactly as the model may have emitted it —
    before layer 4's registry re-check."""

    model_config = ConfigDict(extra="forbid")

    id: str
    action: str
    tool: str = "none"


class PlanDraft(BaseModel):
    """Layer 3. `extra="forbid"` catches any field the schema builder did
    not anticipate; the two validators below catch what `output_config`
    cannot express at all (§4.3)."""

    model_config = ConfigDict(extra="forbid")

    intent: str
    confidence: float
    privacy_level: str
    objective: str
    project_key: str
    agents: list[str]
    tools: list[str]
    steps: list[PlanStepDraft]

    @field_validator("confidence")
    @classmethod
    def _confidence_in_unit_interval(cls, value: float) -> float:
        if not (0.0 <= value <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0 inclusive")
        return value

    @field_validator("steps")
    @classmethod
    def _steps_non_empty_with_unique_ids(cls, value: list[PlanStepDraft]) -> list[PlanStepDraft]:
        if not value:
            raise ValueError("steps must not be empty")
        ids = [step.id for step in value]
        if len(ids) != len(set(ids)):
            raise ValueError("steps[].id must be unique")
        return value


class ValidatedPlanStep:
    """The layer-5 counterpart of `PlanStepDraft`, after layer 4 has
    confirmed the tool/action/permission triple is real. Immutable —
    `__slots__`, no setattr path."""

    __slots__ = ("id", "action", "tool")

    def __init__(self, *, id: str, action: str, tool: str) -> None:  # noqa: A002
        self.id = id
        self.action = action
        self.tool = tool

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"ValidatedPlanStep(id={self.id!r}, action={self.action!r}, tool={self.tool!r})"


class ValidatedPlan:
    """Minted only by `plan_validator.validate_plan()`
    (`ARCHITECTURE_V1.md` §6.1, ADR-004 layer 5 + Amendment 1).

    `raw` carries the original draft as a plain dict, matching the shape
    `plans.raw_json` needs (§7.3) for T11b's `turn.py` to persist — a
    rejected *or* accepted plan is evidence, never a lost log line
    (§6.2). **Flagged for the Architect/DM, not decided here:** §8.3's
    redaction list names `llm_calls.request_messages`/`response_*`,
    `tool_calls.parameters`/`result` and `audit_events.detail` as
    scrubbed before insert; `plans.raw_json` is not on that list. This
    class does not write to the database — T9 owns no DB code — so
    whether `turn.py` must run `redaction.scrub()` on `.raw` before the
    `plans` insert is a question for whoever builds that write path, not
    an assumption baked in here.
    """

    __slots__ = (
        "intent",
        "objective",
        "project_key",
        "agents",
        "tools",
        "steps",
        "plan_id",
        "raw",
    )

    def __init__(
        self,
        *,
        _token: object,
        intent: str,
        objective: str,
        project_key: str,
        agents: list[str],
        tools: list[str],
        steps: list[ValidatedPlanStep],
        plan_id: str,
        raw: dict[str, Any],
    ) -> None:
        if _token is not _VALIDATOR_TOKEN:
            raise TypeError(
                "ValidatedPlan may only be constructed by plan_validator.validate_plan()"
            )
        self.intent = intent
        self.objective = objective
        self.project_key = project_key
        self.agents = agents
        self.tools = tools
        self.steps = steps
        self.plan_id = plan_id
        self.raw = raw

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"ValidatedPlan(plan_id={self.plan_id!r}, intent={self.intent!r}, "
            f"project_key={self.project_key!r}, agents={self.agents!r}, steps={len(self.steps)})"
        )
