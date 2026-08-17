"""Builders for the plan JSON an M1 "plan" LLM call returns, matching the schema shape
worked through in ARCHITECTURE_V1.md §6.1 exactly (field names, the two sentinels
`project_key: "__unknown__"` and `tool: "none"`)."""

from __future__ import annotations

import json
from typing import Any


def valid_plan_dict(
    *, project_key: str = "easy_clean_workforce", confidence: float = 0.92
) -> dict[str, Any]:
    return {
        "intent": "project_status_review",
        "confidence": confidence,
        "privacy_level": "internal",
        "objective": "Check on EasyClean Workforce",
        "project_key": project_key,
        "agents": ["project_manager"],
        "tools": ["github"],
        "steps": [
            {"id": "s1", "action": "resolve_project", "tool": "none"},
            # Tool-bearing "action" values are registry-derived (plan_schema.py's
            # `_tool_bearing_actions()` reads them straight from config/tools.yaml at
            # runtime; plan_validator.py's `_validate_tool_step()` checks
            # `registries.tools.has_operation(step.tool, step.action)`), so this MUST be
            # the real operation name, "list_recent_activity" -- not the
            # "load_recent_activity" spelling in ARCHITECTURE_V1.md §6.1's own static
            # worked example, which is stale relative to the real config/tools.yaml and
            # was never reachable from a real constrained-decoding call in the first
            # place. Found by the Delivery Manager running the full suite on `main`
            # (efd8366) after T11b's merge let requests reach Layer 4 for the first
            # time; BE-1 traced the root cause while proving T11b.
            {"id": "s2", "action": "list_recent_activity", "tool": "github"},
            {"id": "s3", "action": "summarise_activity", "tool": "none"},
        ],
    }


def valid_plan_json(**kwargs: Any) -> str:
    return json.dumps(valid_plan_dict(**kwargs))


def unknown_project_plan_json() -> str:
    """ET-11: the schema's own sentinel for "no registered project matched" —
    ARCHITECTURE_V1.md §6.1: 'project_key: "__unknown__" is how ET-11 is satisfied
    structurally'."""
    d = valid_plan_dict(project_key="__unknown__")
    d["steps"] = [{"id": "s1", "action": "resolve_project", "tool": "none"}]
    return json.dumps(d)


def malformed_plan_text() -> str:
    """ET-7: not valid JSON at all -- simulates what Layer 2 (ARCHITECTURE_V1.md §6.1:
    'the provider never guesses... anything else raises StructuredOutputError') exists
    to catch, i.e. a hypothetical failure of the real constrained-decoding guarantee.
    A FakeProvider/mock server is not bound by that guarantee, which is exactly what
    makes this fault injectable at all."""
    return "I'm not sure how to format this as JSON, but here is my plan: check the repo."


def plan_with_unregistered_agent_json() -> str:
    """ET-7's other shape: superficially well-formed JSON that Layer 4 (the registry
    re-check) must still reject, in case Layer 1's constrained decoding is ever bypassed
    (ADR-004: 'Layer 4 is what still holds if a provider without constrained decoding
    is ever swapped in')."""
    d = valid_plan_dict()
    d["agents"] = ["not_a_real_agent"]
    return json.dumps(d)
