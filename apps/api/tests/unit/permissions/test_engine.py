"""`sunil.core.permissions.engine` — the T7 decision function (§9.2, ET-4).

Ownership: T7 owns `apps/api/tests/unit/permissions/**`
(`docs/M1_BUILD_PLAN.md` §5 T18 "backend engineers own `tests/unit/**` for
their own modules").
"""

from __future__ import annotations

import pytest
from sunil.core.permissions.engine import Decision, PermissionResult, decide
from sunil.core.registry.permissions import PermissionRegistry


def _registry(grants: dict[str, dict[str, dict[str, str]]]) -> PermissionRegistry:
    return PermissionRegistry(grants)


def test_decide_returns_allow_for_an_explicit_grant() -> None:
    registry = _registry({"project_manager": {"github": {"list_recent_activity": "allow"}}})

    result = decide(
        registry, agent_id="project_manager", tool="github", operation="list_recent_activity"
    )

    assert result == PermissionResult(
        decision=Decision.ALLOW,
        reason="explicit grant",
        source="config:project_manager.github.list_recent_activity",
    )


def test_decide_returns_ask_user_for_an_explicit_ask_user_grant() -> None:
    """FR-121: the value must be legal end to end even though no M1 grant
    actually resolves to it."""
    registry = _registry({"project_manager": {"github": {"delete_repo": "ask_user"}}})

    result = decide(registry, agent_id="project_manager", tool="github", operation="delete_repo")

    assert result.decision is Decision.ASK_USER


def test_decide_denies_a_known_agent_and_tool_with_no_grant_for_the_operation() -> None:
    registry = _registry({"project_manager": {"github": {"list_recent_activity": "allow"}}})

    result = decide(registry, agent_id="project_manager", tool="github", operation="delete_repo")

    assert result.decision is Decision.DENY
    assert result.reason == "no explicit grant"
    assert result.source == "default-deny"


def test_decide_denies_an_unregistered_tool() -> None:
    registry = _registry({"project_manager": {"github": {"list_recent_activity": "allow"}}})

    result = decide(registry, agent_id="project_manager", tool="slack", operation="post_message")

    assert result.decision is Decision.DENY
    assert result.source == "default-deny"


def test_decide_denies_an_unregistered_agent() -> None:
    registry = _registry({"project_manager": {"github": {"list_recent_activity": "allow"}}})

    result = decide(
        registry, agent_id="some_new_agent", tool="github", operation="list_recent_activity"
    )

    assert result.decision is Decision.DENY
    assert result.source == "default-deny"


def test_empty_permission_config_denies_everything() -> None:
    """The named test `docs/M1_BUILD_PLAN.md` T7 requires — this is what
    makes "default-deny" a fact rather than a description. An empty grant
    map is the most permissive-looking config a typo could produce
    (nothing has been explicitly denied) and it must still deny every
    request."""
    registry = _registry({})

    result = decide(
        registry, agent_id="project_manager", tool="github", operation="list_recent_activity"
    )

    assert result.decision is Decision.DENY
    assert result.source == "default-deny"


@pytest.mark.parametrize(
    ("agent_id", "tool", "operation"),
    [
        ("project_manager", "github", "delete_repo"),
        ("project_manager", "github", "list_recent_activity"),
        ("attacker_agent", "github", "list_recent_activity"),
        ("project_manager", "shell", "run"),
    ],
)
def test_every_non_granted_triple_denies_against_an_empty_registry(
    agent_id: str, tool: str, operation: str
) -> None:
    """Structural default-deny again, but swept across several shapes of
    request against the emptiest possible config, so the guarantee is not
    accidentally scoped to one example agent/tool pair."""
    registry = _registry({})

    result = decide(registry, agent_id=agent_id, tool=tool, operation=operation)

    assert result.decision is Decision.DENY


def test_decision_is_scoped_to_the_exact_operation_not_the_whole_tool() -> None:
    """A grant on one operation must not leak an implicit ALLOW onto a
    sibling operation of the same tool — the fence is per-operation, not
    per-tool."""
    registry = _registry({"project_manager": {"github": {"list_recent_activity": "allow"}}})

    result = decide(registry, agent_id="project_manager", tool="github", operation="delete_repo")

    assert result.decision is Decision.DENY
