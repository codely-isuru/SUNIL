"""Layer 1 of ADR-004 — the JSON Schema built from the live registries at
runtime (`ARCHITECTURE_V1.md` §6.1).

`build_plan_schema(registries)` emits the schema passed as Anthropic's
`output_config={"format": {"type": "json_schema", "schema": ...}}`
(§4.3). Because the provider enforces the schema by **constrained
decoding**, an unregistered agent, tool or project name is not a
reachable token sequence — the whitelist below is part of the grammar,
not a post-hoc filter. `test_plan_schema_enums_match_registries` fails
the moment this function's output and the registries it was built from
drift apart (ADR-004 "Consequences").

The schema stays inside the verified `output_config` feature envelope
(§4.3): no `minimum`/`maximum`, no `minLength`, no nullable union types.
`additionalProperties: false` everywhere it is legal, and the two
sentinels — `project_key: "__unknown__"` and `steps[].tool: "none"` —
keep every field a plain string enum.

**Flagged assumption, not a registry-backed fact — confirm with the
Architect:** none of T3's six `config/*.yaml` files models a "plan
intent" or "plan step action" vocabulary; `agents.yaml` holds role and
tool grants, not the shape of a plan. M1 has exactly one agent running a
fixed three-step pipeline (ADR-000 Q2, §33.2 "executes a fixed
pipeline"), so `SUPPORTED_INTENTS` and `NON_TOOL_ACTIONS` below are
small, explicit, code-level constants co-located with the schema
builder, not a seventh YAML file invented unilaterally (`M1_BUILD_PLAN.md`
§0.2 rule 3 forbids adding to §14.3 without an escalation; this sidesteps
that by not being a dependency, but the *vocabulary itself* is still an
assumption worth an Architect sign-off before M2 adds a second agent).
Every tool-bearing action, by contrast, **is** registry-derived: it must
be a real operation name in `config/tools.yaml`.
"""

from __future__ import annotations

from typing import Any

from sunil.core.registry import Registries
from sunil.core.registry.projects import UNKNOWN_PROJECT_KEY

# The one intent M1 recognises, plus the catch-all that routes to
# `unknown_project`/`plan_rejected`-style failure handling rather than a
# crash. Not sourced from any config/*.yaml file — see the module
# docstring's flagged assumption.
SUPPORTED_INTENTS: tuple[str, ...] = ("project_status_review", "unsupported")

# M1's fixed pipeline has exactly two steps that do not call a tool:
# resolving which project was meant, and writing the final summary. Every
# other legal action names a real operation in config/tools.yaml (see
# `_tool_bearing_actions` below) so at least the tool-invoking half of
# this enum is registry-derived and cannot drift silently.
NON_TOOL_ACTIONS: tuple[str, ...] = ("resolve_project", "summarise_activity")

# M1 has exactly one privacy level; the field exists (NFR-010 threads it
# through from day one) but only "internal" is legal until V2 differentiates.
SUPPORTED_PRIVACY_LEVELS: tuple[str, ...] = ("internal",)

_NO_TOOL_SENTINEL = "none"


def _tool_bearing_actions(registries: Registries) -> set[str]:
    """Every operation name across every registered tool — the part of
    the `action` enum that *is* registry-derived."""
    actions: set[str] = set()
    for tool_name in registries.tools.tool_names():
        tool_def = registries.tools.get_tool(tool_name)
        actions.update(tool_def.operations.keys())
    return actions


def build_plan_schema(registries: Registries) -> dict[str, Any]:
    """The runtime JSON Schema for a plan draft, per `ARCHITECTURE_V1.md`
    §6.1. Pure function of `registries` — call it again whenever the
    registries change (ADR-004 "Consequences": "the schema builder must
    be rebuilt whenever the registries change").
    """
    agent_ids = sorted(registries.agents.keys())
    tool_names = sorted(registries.tools.tool_names())
    project_keys = sorted([*registries.projects.keys(), UNKNOWN_PROJECT_KEY])
    action_names = sorted({*NON_TOOL_ACTIONS, *_tool_bearing_actions(registries)})
    step_tool_names = sorted([*tool_names, _NO_TOOL_SENTINEL])

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
            "project_key": {"type": "string", "enum": project_keys},
            "agents": {"type": "array", "items": {"type": "string", "enum": agent_ids}},
            "tools": {"type": "array", "items": {"type": "string", "enum": tool_names}},
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["id", "action"],
                    "properties": {
                        "id": {"type": "string"},
                        "action": {"type": "string", "enum": action_names},
                        "tool": {"type": "string", "enum": step_tool_names},
                    },
                },
            },
        },
    }
