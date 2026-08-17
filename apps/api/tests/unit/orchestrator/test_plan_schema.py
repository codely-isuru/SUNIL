"""`sunil.core.orchestrator.plan_schema` — layer 1 (§6.1)."""

from __future__ import annotations

from sunil.core.orchestrator.plan_schema import build_plan_schema
from sunil.core.registry.loader import Registries
from sunil.core.registry.projects import UNKNOWN_PROJECT_KEY


def test_plan_schema_enums_match_registries(registries: Registries) -> None:
    """The named ADR-004 §6.3 test. If the schema builder and the
    registries it reads ever drift, an unregistered name becomes a
    reachable token sequence again — this is the test that would catch
    that regression."""
    schema = build_plan_schema(registries)

    props = schema["properties"]
    assert set(props["agents"]["items"]["enum"]) == set(registries.agents.keys())
    assert set(props["tools"]["items"]["enum"]) == set(registries.tools.tool_names())
    assert set(props["project_key"]["enum"]) == {
        *registries.projects.keys(),
        UNKNOWN_PROJECT_KEY,
    }

    step_props = props["steps"]["items"]["properties"]
    assert set(step_props["tool"]["enum"]) == {*registries.tools.tool_names(), "none"}
    # Every tool-bearing action in the enum must be a real operation of
    # some registered tool.
    all_operations = {
        op
        for tool_name in registries.tools.tool_names()
        for op in registries.tools.get_tool(tool_name).operations
    }
    assert all_operations <= set(step_props["action"]["enum"])


def test_plan_schema_stays_inside_the_output_config_feature_envelope(
    registries: Registries,
) -> None:
    """§4.3: no `minimum`/`maximum`, no `minLength`, no nullable union
    types anywhere in the schema — those are outside Anthropic's verified
    `output_config` feature envelope and Pydantic (layer 3) is what
    enforces the bounds instead."""
    schema = build_plan_schema(registries)

    def walk(node: object) -> None:
        if isinstance(node, dict):
            assert "minimum" not in node
            assert "maximum" not in node
            assert "minLength" not in node
            assert "maxLength" not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)


def test_plan_schema_forbids_additional_properties_on_the_top_level_and_each_step(
    registries: Registries,
) -> None:
    schema = build_plan_schema(registries)

    assert schema["additionalProperties"] is False
    assert schema["properties"]["steps"]["items"]["additionalProperties"] is False


def test_plan_schema_requires_every_top_level_field(registries: Registries) -> None:
    schema = build_plan_schema(registries)

    assert set(schema["required"]) == {
        "intent",
        "confidence",
        "privacy_level",
        "objective",
        "project_key",
        "agents",
        "tools",
        "steps",
    }


def test_plan_schema_requires_every_step_field_too(registries: Registries) -> None:
    """T24: OpenAI's `strict: true` structured-output mode (verified from
    the installed SDK's own `openai/lib/_pydantic.py` strict-schema
    helper — see `sunil/providers/openai.py`) requires *every* property
    listed in `required`; a property that is merely absent from
    `required` is not legal "optional" under that mode, unlike Anthropic's
    envelope where it is. `tool` was the one property on the whole schema
    not in its object's own `required` list — a step legitimately has no
    tool, but the enum already carries the `"none"` sentinel for exactly
    that case (see the module docstring), so the fix is to require the
    property and let `"none"` express absence, not to leave it optional.
    """
    schema = build_plan_schema(registries)

    step_schema = schema["properties"]["steps"]["items"]
    assert set(step_schema["required"]) == set(step_schema["properties"].keys())
    assert set(step_schema["required"]) == {"id", "action", "tool"}
