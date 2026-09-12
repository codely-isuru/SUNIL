"""The developer agent's MOUNT — `config/tools.yaml` + `config/permissions.yaml`.

Stream F built the governed seam against a test double (`harness.StubGitAdapter`)
and recorded the two config rows it needed as handover requests, because neither
file was that lane's (`docs/tasks/S2-F-openhands.md` §5.1/§5.2). This module is
those rows asserted on the REPOSITORY's own files, in the pattern
`tests/unit/n8n/test_mount.py` set:

* the operations exist and are SUNIL-declared writes;
* the params model is the one the agent actually builds arguments for — pinned
  against the harness double, so the double cannot drift away from the config it
  stands in for;
* the decision is read through the production `decide()`, not off the YAML
  string, and `merge_main` is ASK_USER for the developer while nobody else holds
  either row at all.

ADR-030 §4 is the policy being pinned: `push_branch: allow` (the agent's own
branch, which `validate_branch` has already refused to let be a protected one),
`merge_main: ask_user` (parks via C4, and `main` is exactly what the branch rule
protects).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sunil.core.permissions.engine import decide
from sunil.core.permissions.registry import load_permissions
from sunil.core.tool_framework.base import PermissionDecision
from sunil.core.tool_framework.tools_config import (
    cross_validate_permissions,
    load_tools_config,
)

from tests.unit.agents.harness import MergeMainParams, PushBranchParams

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOLS_YAML = REPO_ROOT / "config" / "tools.yaml"
PERMISSIONS_YAML = REPO_ROOT / "config" / "permissions.yaml"
AGENTS_YAML = REPO_ROOT / "config" / "agents.yaml"

GIT_TOOL = "github_mcp"
#: ADR-030 §4's policy, as a table: operation -> the decision the owner gets.
GOVERNED = {
    "push_branch": PermissionDecision.ALLOW,
    "merge_main": PermissionDecision.ASK_USER,
}
#: The exact argument shape the agent builds itself (S2-F-openhands.md §2,
#: control 3: "It cannot choose the params").
EXPECTED_FIELDS = {"project_key", "branch", "base_branch"}


def _tools():
    return load_tools_config(TOOLS_YAML)


@pytest.mark.parametrize("operation", sorted(GOVERNED))
def test_the_git_write_is_a_configured_operation_with_sunil_owned_metadata(
    operation: str,
) -> None:
    """`read_only: false` is SUNIL's statement about these two, not the MCP
    server's: both write to a remote nobody here controls."""
    block = _tools().tools[GIT_TOOL].operations[operation]

    assert block.read_only is False
    assert block.timeout_s > 0
    assert block.params_model.model_config.get("extra") == "forbid"
    assert set(block.params_model.model_fields) == EXPECTED_FIELDS


@pytest.mark.parametrize("operation", sorted(GOVERNED))
def test_the_configured_params_model_matches_the_shape_the_agent_calls_with(
    operation: str,
) -> None:
    """The harness double is what every Stream F test runs against; this config
    is what production wires. A divergence between them would make that whole
    suite green against a shape the chokepoint would reject."""
    pin = {"push_branch": PushBranchParams, "merge_main": MergeMainParams}[operation]
    configured = _tools().tools[GIT_TOOL].operations[operation].params_model

    assert set(configured.model_fields) == set(pin.model_fields)


@pytest.mark.parametrize(("operation", "expected"), sorted(GOVERNED.items()))
def test_adr_030_section_4_policy_is_what_the_engine_decides(
    operation: str, expected: PermissionDecision
) -> None:
    result = decide(
        load_permissions(PERMISSIONS_YAML),
        agent_id="developer",
        tool=GIT_TOOL,
        operation=operation,
    )

    assert result.decision is expected
    assert result.source == f"config:developer.{GIT_TOOL}.{operation}"


@pytest.mark.parametrize("operation", sorted(GOVERNED))
def test_no_other_agent_gains_the_git_writes(operation: str) -> None:
    """The rows are scoped to one agent. A second agent that could push on the
    developer's grant would be an authority nobody reviewed, and default-deny is
    what must answer for it."""
    permissions = load_permissions(PERMISSIONS_YAML)

    for agent_id in permissions.agent_ids():
        if agent_id == "developer":
            continue
        result = decide(permissions, agent_id=agent_id, tool=GIT_TOOL, operation=operation)
        assert result.decision is PermissionDecision.DENY
        assert result.source == "default-deny"


def test_the_engine_itself_has_no_grant_anywhere() -> None:
    """The delegation to the sandbox is NOT a tool call (S2-F-openhands.md §2).
    A `developer.fix_and_pr` triple appearing in either file would mean somebody
    re-modelled it as one — a tool with no adapter behind it."""
    permissions = load_permissions(PERMISSIONS_YAML)

    assert "fix_and_pr" not in {
        operation for _tool, operation in permissions.referenced_tool_operations()
    }
    assert "fix_and_pr" not in {
        operation
        for block in _tools().tools.values()
        for operation in block.operations
    }


def test_every_planning_grant_the_developer_holds_is_a_configured_operation() -> None:
    """`config/agents.yaml` (layer 4's planning grant) and `config/tools.yaml`
    (the catalogue) are cross-validated for permissions but NOT for agents — so
    a grant naming an operation nothing exposes fails at request time, silently,
    as if the planner had hallucinated it."""
    agents = yaml.safe_load(AGENTS_YAML.read_text("utf-8"))["agents"]
    configured = _tools().tools

    grants = agents["developer"]["tools"]
    assert grants, "the developer holds no planning grant - this would pass vacuously"
    for tool, operations in grants.items():
        assert tool in configured, f"agents.yaml grants developer the unknown tool {tool!r}"
        for operation in operations:
            assert operation in configured[tool].operations, (
                f"agents.yaml grants developer {tool}.{operation}, which "
                "config/tools.yaml does not expose"
            )


def test_the_only_unattended_write_in_the_matrix_is_the_developers_branch_push() -> None:
    """Repo-wide, and the reason this test is here rather than scoped to one
    server: `allow` on a `read_only: false` operation is a write nobody sees
    happen. Exactly one exists, ADR-030 §4 put it there on the record, and the
    next one added trips this instead of arriving quietly.

    (`tests/unit/n8n/test_mount.py` asserts the same shape for `n8n_mcp` alone;
    this is the whole file, so a new server cannot be added outside it.)
    """
    permitted_unattended_writes = {("developer", GIT_TOOL, "push_branch")}

    permissions = load_permissions(PERMISSIONS_YAML)
    configured = _tools().tools

    unattended_writes = set()
    for agent_id in permissions.agent_ids():
        for tool, operation in permissions.referenced_tool_operations():
            if permissions.grant_for(agent_id, tool, operation) != "allow":
                continue
            block = configured[tool].operations[operation]
            if not block.read_only:
                unattended_writes.add((agent_id, tool, operation))

    assert unattended_writes == permitted_unattended_writes


def test_the_repository_mount_cross_validates() -> None:
    """Startup's own check (`api/wiring.py`), run here so a config edit cannot
    land red: no grant may name a tool or operation `tools.yaml` omits."""
    cross_validate_permissions(_tools(), load_permissions(PERMISSIONS_YAML))
