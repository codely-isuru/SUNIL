"""The developer agent's MOUNT — DORMANT state (ruling R16, 2026-09-12).

`github_mcp` is commented out of `config/tools.yaml`, and its permission rows
out of `config/permissions.yaml`, until the w2r3 parcel lands a VERIFIED pin
(docs/tasks/integration-w1-rulings.md R16): no live server advertises the four
SUNIL operation names, so any executable row is a whole-tool startup refusal
under ADR-034's drift check. This module pins the dormant state so it cannot
half-return: the rows come back TOGETHER (R15's atomicity rule) or not at all.
ADR-030 §4 is unchanged as policy; its decisions return with the parcel.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from sunil.core.permissions.engine import decide
from sunil.core.permissions.registry import load_permissions
from sunil.core.tool_framework.base import PermissionDecision
from sunil.core.tool_framework.tools_config import (
    cross_validate_permissions,
    load_tools_config,
)
from sunil.tools.mcp.params import MergeMainParams, PushBranchParams

from tests.unit.agents import harness

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOLS_YAML = REPO_ROOT / "config" / "tools.yaml"
PERMISSIONS_YAML = REPO_ROOT / "config" / "permissions.yaml"
AGENTS_YAML = REPO_ROOT / "config" / "agents.yaml"

#: The argument shape the w2r3 approval flow binds to (S2-F §2 control 3).
EXPECTED_FIELDS = {"project_key", "branch", "base_branch"}


def test_github_mcp_is_dormant_not_half_wired() -> None:
    """Whole-surface dormancy: no tool block, no permission row anywhere. A
    permission row returning without the tool block is the startup-refusal
    state R15's atomicity rule forbids — this is the tripwire."""
    tools = load_tools_config(TOOLS_YAML)
    permissions = load_permissions(PERMISSIONS_YAML)

    assert "github_mcp" not in tools.tools
    assert not [
        pair for pair in permissions.referenced_tool_operations() if pair[0] == "github_mcp"
    ]
    cross_validate_permissions(tools, permissions)


def test_the_git_writes_are_default_deny_for_everyone_while_dormant() -> None:
    """ADR-030 §4's decisions (`allow` / `ask_user`, developer only) return
    with the w2r3 parcel; until then structural default-deny is the decision
    of record, for the developer and everyone else alike."""
    permissions = load_permissions(PERMISSIONS_YAML)

    for agent_id in permissions.agent_ids():
        for operation in ("push_branch", "merge_main"):
            result = decide(
                permissions, agent_id=agent_id, tool="github_mcp", operation=operation
            )
            assert result.decision is PermissionDecision.DENY
            assert result.source == "default-deny"


def test_no_unattended_write_exists_while_github_mcp_is_dormant() -> None:
    """The W2R2 tripwire, dormant edition: ADR-030 §4's
    `developer.github_mcp.push_branch` is the ONE ruled exception and it is out
    of the matrix until the w2r3 parcel — so today the set is EMPTY, and any
    `allow` on a `read_only: false` operation arriving before that parcel
    trips here instead of arriving quietly."""
    permissions = load_permissions(PERMISSIONS_YAML)
    configured = load_tools_config(TOOLS_YAML).tools

    unattended_writes = {
        (agent_id, tool, operation)
        for agent_id in permissions.agent_ids()
        for tool, operation in permissions.referenced_tool_operations()
        if permissions.grant_for(agent_id, tool, operation) == "allow"
        and not configured[tool].operations[operation].read_only
    }

    assert unattended_writes == set()


def test_the_dormant_params_models_keep_the_approved_shape() -> None:
    """The args_hash shape survives dormancy: `sunil/tools/mcp/params.py`
    stays in the tree (the `RunWorkflowParams` precedent, R15), and the
    harness double every Stream F test runs against stays pinned to it."""
    for model, pin in (
        (PushBranchParams, harness.PushBranchParams),
        (MergeMainParams, harness.MergeMainParams),
    ):
        assert model.model_config.get("extra") == "forbid"
        assert set(model.model_fields) == EXPECTED_FIELDS
        assert set(model.model_fields) == set(pin.model_fields)


def test_the_developer_planning_grants_are_exactly_the_dormant_pair() -> None:
    """`config/agents.yaml` keeps the two planning grants: structurally inert
    while the catalogue holds no github_mcp (R1's grounds — layer 4 checks the
    adapter-built catalogue first, and the plan-schema enum is
    catalogue-built). A THIRD grant, or a grant on another tool, still trips
    this before it can pass unreviewed."""
    agents = yaml.safe_load(AGENTS_YAML.read_text("utf-8"))["agents"]

    assert agents["developer"]["tools"] == {
        "github_mcp": ["push_branch", "merge_main"]
    }
