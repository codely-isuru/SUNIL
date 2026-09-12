"""Layer 1 — the JSON Schema built from the live registries at runtime.

`build_plan_schema(agents=…, catalogue=…, projects=…)` produces the schema sent
as the provider's `json_schema` (C2 §2: non-`None` means structured output is
REQUIRED — the plan stage always sets it, free-form never plans). Because the
provider enforces it by **constrained decoding**, an unregistered agent, tool or
operation is not a reachable token sequence: the whitelist is part of the
grammar, not a post-hoc filter. Layer 4 re-checks the same facts anyway
(`plan_validator`), because this layer is the provider's guarantee and that one
is ours.

Two constraints on the emitted schema, both learned the hard way:

* **Every property appears in its object's `required`**, including `tool` and
  `operation`. OpenAI's `strict: true` structured-output mode rejects a schema
  where a property is merely absent from `required`; Anthropic permits
  `required` freely, so naming already-legal enum values narrows nothing there.
  A step with no tool emits the `"none"` sentinel explicitly rather than
  omitting the key.
* **`params` stays an open object** (no `additionalProperties: false`): each
  tool operation has its own Pydantic params model with `extra="forbid"`, and
  that model — reached through the C1 chokepoint — is the real validator.
  Restating per-tool param shapes here would be a second, drifting copy of
  Stream A's config.
"""

from __future__ import annotations

from typing import Any, Mapping

from sunil.core.orchestrator.plan_models import NO_TOOL
from sunil.core.orchestrator.plan_validator import ToolCatalogue

#: The intent vocabulary. Small and code-level on purpose: no `config/*.yaml`
#: models a plan-intent vocabulary, and inventing a seventh config file for it
#: would be a unilateral architecture change. `unsupported` is the honest
#: catch-all that routes to a failure rather than to an invented action.
SUPPORTED_INTENTS: tuple[str, ...] = (
    "project_status_review",
    "tool_operation",
    "question_answer",
    "unsupported",
)

#: Actions that call no tool. Every OTHER legal action is `tool_call`, whose
#: tool/operation pair is registry-derived below.
NON_TOOL_ACTIONS: tuple[str, ...] = ("resolve_project", "summarise_activity", "answer")

TOOL_CALL_ACTION = "tool_call"

#: Privacy levels a plan may claim. Mirrors C2's `PrivacyClass` by value; the
#: router — not the plan — decides where a privacy class may be served from, so
#: this list widens only when that policy does.
SUPPORTED_PRIVACY_LEVELS: tuple[str, ...] = ("public", "internal", "confidential", "local_only")


def build_plan_schema(
    *,
    agents: Mapping[str, Any],
    catalogue: ToolCatalogue,
    projects: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The runtime JSON Schema for a plan draft. A pure function of the
    registries — rebuild it whenever they change."""
    agent_ids = sorted(agents)
    tool_names = sorted(catalogue.operations_by_tool)
    operations = sorted(
        {operation for ops in catalogue.operations_by_tool.values() for operation in ops}
    )
    project_keys = sorted(projects or {})

    project_property: dict[str, Any] = (
        {"type": ["string", "null"], "enum": [*project_keys, None]}
        if project_keys
        else {"type": ["string", "null"], "enum": [None]}
    )

    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "intent",
            "confidence",
            "privacy_level",
            "objective",
            "project_key",
            "agents",
            "tools",
            "steps",
        ],
        "properties": {
            "intent": {"type": "string", "enum": list(SUPPORTED_INTENTS)},
            "confidence": {"type": "number"},
            "privacy_level": {"type": "string", "enum": list(SUPPORTED_PRIVACY_LEVELS)},
            "objective": {"type": "string"},
            "project_key": project_property,
            "agents": {"type": "array", "items": {"type": "string", "enum": agent_ids}},
            "tools": {"type": "array", "items": {"type": "string", "enum": tool_names}},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "action", "tool", "operation", "params"],
                    "properties": {
                        "id": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": sorted({*NON_TOOL_ACTIONS, TOOL_CALL_ACTION}),
                        },
                        "tool": {"type": "string", "enum": [*tool_names, NO_TOOL]},
                        "operation": {"type": "string", "enum": [*operations, NO_TOOL]},
                        # Open object by design — the operation's own params
                        # model (extra="forbid") validates it at the chokepoint.
                        "params": {"type": "object"},
                    },
                },
            },
        },
    }
