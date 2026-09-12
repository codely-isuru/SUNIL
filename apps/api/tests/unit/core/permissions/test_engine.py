"""Unit tests — the permission engine (agent × tool × operation).

C1 §2.2 fixes the return shape (``PermissionResult``, "default-deny is
structural in the engine, not config"); ADR-034 fixes the mapping (an MCP
server is a tool, an MCP tool is an operation, so the M1 engine is reused
byte-for-byte); the M1 reference is ``main:.../core/permissions/engine.py``.

The load-bearing test is the first one: with a literal empty grant map — and
with NO registry at all — every triple denies. That property is the engine's
own control flow, so no edit to ``config/permissions.yaml`` can weaken it.
"""

from __future__ import annotations

import pytest

from sunil.core.permissions.engine import PermissionEngineHook, decide
from sunil.core.permissions.registry import (
    PermissionRegistry,
    PermissionsConfigError,
    load_permissions,
)
from sunil.core.tool_framework.base import PermissionDecision, PermissionResult

TRIPLE = {"agent_id": "project_manager", "tool": "github_mcp", "operation": "issues_close"}


def test_empty_registry_denies_everything() -> None:
    result = decide(PermissionRegistry({}), **TRIPLE)

    assert isinstance(result, PermissionResult)
    assert result.decision is PermissionDecision.DENY
    assert result.reason == "no grant for this triple (default deny)"
    assert result.source == "default-deny"


def test_no_registry_at_all_still_denies() -> None:
    """A caller that forgot to wire a registry must not get an allow."""
    assert decide(**TRIPLE).decision is PermissionDecision.DENY


@pytest.mark.parametrize(
    "granted,expected",
    [
        ("allow", PermissionDecision.ALLOW),
        ("ask_user", PermissionDecision.ASK_USER),
        ("deny", PermissionDecision.DENY),
    ],
)
def test_explicit_grant_is_returned_with_its_source_path(granted, expected) -> None:
    registry = PermissionRegistry(
        {"project_manager": {"github_mcp": {"issues_close": granted}}}
    )

    result = decide(registry, **TRIPLE)

    assert result.decision is expected
    assert result.reason == "granted"
    assert result.source == "config:project_manager.github_mcp.issues_close"


@pytest.mark.parametrize(
    "override",
    [
        {"agent_id": "developer"},
        {"tool": "github"},
        {"operation": "issues_open"},
    ],
)
def test_a_grant_never_leaks_to_a_neighbouring_triple(override) -> None:
    registry = PermissionRegistry(
        {"project_manager": {"github_mcp": {"issues_close": "allow"}}}
    )

    result = decide(registry, **{**TRIPLE, **override})

    assert result.decision is PermissionDecision.DENY
    assert result.source == "default-deny"


def test_registry_reports_referenced_pairs_for_startup_cross_validation() -> None:
    registry = PermissionRegistry(
        {
            "project_manager": {
                "github_mcp": {"issues_close": "ask_user"},
                "github": {"list_recent_activity": "allow"},
            },
            "developer": {"github_mcp": {"issues_close": "deny"}},
        }
    )

    assert registry.referenced_tool_operations() == {
        ("github_mcp", "issues_close"),
        ("github", "list_recent_activity"),
    }
    assert sorted(registry.agent_ids()) == ["developer", "project_manager"]


def test_permission_engine_hook_satisfies_the_c1_hook_shape() -> None:
    """C1 §2.2's ``PermissionHook`` is keyword-only — the manager calls
    ``hook(agent_id=..., tool=..., operation=...)``, so the production adapter
    over the engine must accept exactly that."""
    hook = PermissionEngineHook(
        PermissionRegistry({"project_manager": {"github_mcp": {"issues_close": "ask_user"}}})
    )

    assert hook(**TRIPLE).decision is PermissionDecision.ASK_USER
    assert hook(agent_id="nobody", tool="x", operation="y").decision is (
        PermissionDecision.DENY
    )


# --- the loader ----------------------------------------------------------- #
def _write(tmp_path, text: str):
    path = tmp_path / "permissions.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_permissions_reads_the_grant_tree(tmp_path) -> None:
    path = _write(
        tmp_path,
        "version: 1\nagents:\n  project_manager:\n    github_mcp:\n"
        "      issues_close: ask_user\n",
    )

    registry = load_permissions(path)

    assert registry.grant_for("project_manager", "github_mcp", "issues_close") == "ask_user"
    assert registry.grant_for("project_manager", "github_mcp", "issues_open") is None


@pytest.mark.parametrize(
    "text,message",
    [
        ("version: 2\nagents: {}\n", "expected version: 1"),
        ("version: 1\nagents: []\n", "'agents' must be a mapping"),
        ("version: 1\nagents:\n  pm: 3\n", "must be a mapping"),
        ("version: 1\nagents:\n  pm:\n    github: 3\n", "operation -> decision"),
        (
            "version: 1\nagents:\n  pm:\n    github:\n      op: maybe\n",
            "invalid decision",
        ),
    ],
)
def test_load_permissions_refuses_a_malformed_file(tmp_path, text, message) -> None:
    """Fail closed and LOUD: a typo'd decision value must not load as "some
    truthy grant", and it must not load as a silent deny either — a file the
    owner believes grants something must either parse or refuse to boot."""
    with pytest.raises(PermissionsConfigError, match=message):
        load_permissions(_write(tmp_path, text))


def test_load_permissions_on_a_missing_file_is_an_error_not_an_empty_allow(tmp_path) -> None:
    with pytest.raises(PermissionsConfigError, match="not found"):
        load_permissions(tmp_path / "nope.yaml")


def test_the_shipped_repo_config_loads_and_grants_only_reviewed_triples() -> None:
    """``config/permissions.yaml`` as committed: every grant is a triple a human
    reviewed (ADR-034 — new operations arrive by config PR, never by a server
    advertising them).

    Growth-pinned deliberately: the agent list is asserted WHOLE, so an agent
    appearing in that file has to come past this test. W2R2 added ``developer``
    (ADR-030 §4, Stream F).

    This test used to claim in passing that "nothing is granted ``allow`` that
    is not read-only". It never asserted it, and as of ADR-030 §4 it is no
    longer true — ``developer.github_mcp.push_branch`` is an unattended WRITE,
    deliberately. The rule now has a home that ENFORCES it:
    ``tests/unit/agents/test_developer_mount.py::
    test_the_only_unattended_write_in_the_matrix_is_the_developers_branch_push``
    checks every ``allow`` row in this file against ``read_only`` in
    ``config/tools.yaml`` and admits exactly one named exception.
    """
    from pathlib import Path

    repo_config = Path(__file__).resolve().parents[6] / "config" / "permissions.yaml"
    registry = load_permissions(repo_config)

    assert registry.agent_ids() == ["project_manager", "developer"]
    assert registry.grant_for("project_manager", "github", "list_recent_activity") == "allow"
    assert registry.grant_for("project_manager", "github_mcp", "issues_close") == "ask_user"
    assert registry.grant_for("project_manager", "github_mcp", "repos_delete") is None
    assert registry.grant_for("developer", "github_mcp", "push_branch") == "allow"
    assert registry.grant_for("developer", "github_mcp", "merge_main") == "ask_user"
    # The delegation to the execution engine is not a tool call, so it has no
    # row here and none in config/tools.yaml (S2-F-openhands.md §2).
    assert registry.grant_for("developer", "github_mcp", "fix_and_pr") is None
