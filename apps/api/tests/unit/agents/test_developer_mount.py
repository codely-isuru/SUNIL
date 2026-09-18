"""The developer agent's MOUNT — LIVE state (w2r3 parcel, ruling R16).

`github_mcp` was dormant from 2026-09-12 (the pinned server was upstream-dead and
advertised none of SUNIL's names). The w2r3 parcel re-landed it on 2026-09-16
behind R16 part 2's capture gate: the official `github/github-mcp-server` v1.12.2
was booted, its `tools/list` captured verbatim (`docs/tasks/S3-github.md` §0,
pinned in `tests/unit/github_mcp/`), and SUNIL's operation names bound to the
captured verbs via ADR-034 Amendment 1.

Three of the four operations are live. **`push_branch` is not, and this module is
what stops it returning by accident**: R16 part 4 ruled its executor toward the
engine's own sandbox-scoped token and the final shape to the engine-enablement
ADR, which has not landed. Parcel step 5, verbatim: "the parcel must not invent
the push executor."

So the invariant this module carries across the re-landing is the one that
mattered all along — **there is still no unattended write anywhere in the
matrix** — and it now has to hold against a CONFIGURED tool rather than an absent
one, which is the only version of it worth having.
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

#: The argument shape the approval flow binds to (S2-F §2 control 3) — unchanged
#: by the composition: `merge_main` is still ONE approval over THESE three.
EXPECTED_FIELDS = {"project_key", "branch", "base_branch"}


def test_github_mcp_is_wired_whole_not_half() -> None:
    """R15's atomicity rule, now read forwards: the tool block and its permission
    rows are BOTH present, and every granted operation is a declared one.
    `cross_validate_permissions` is the startup check that would refuse to boot
    on a half-landed parcel."""
    tools = load_tools_config(TOOLS_YAML)
    permissions = load_permissions(PERMISSIONS_YAML)

    block = tools.tools["github_mcp"]
    assert set(block.operations) == {"issues_list", "issues_close", "merge_main"}
    assert {
        pair for pair in permissions.referenced_tool_operations() if pair[0] == "github_mcp"
    } == {
        ("github_mcp", "issues_list"),
        ("github_mcp", "issues_close"),
        ("github_mcp", "merge_main"),
    }
    cross_validate_permissions(tools, permissions)


def test_merge_main_is_the_developers_ask_user_row_and_nobody_elses() -> None:
    """ADR-030 §4's decision, restored: the owner decides every merge, and the
    grant belongs to the developer alone."""
    permissions = load_permissions(PERMISSIONS_YAML)

    developer = decide(
        permissions, agent_id="developer", tool="github_mcp", operation="merge_main"
    )
    assert developer.decision is PermissionDecision.ASK_USER

    for agent_id in permissions.agent_ids():
        if agent_id == "developer":
            continue
        other = decide(
            permissions, agent_id=agent_id, tool="github_mcp", operation="merge_main"
        )
        assert other.decision is PermissionDecision.DENY
        assert other.source == "default-deny"


def test_push_branch_is_still_default_deny_for_everyone() -> None:
    """R16 part 4 / parcel step 5: `push_branch` did NOT come back with the
    parcel. It is not a configured operation and it holds no row, so structural
    default-deny remains the decision of record — for the developer and everyone
    else alike — until the engine-enablement ADR rules its executor."""
    permissions = load_permissions(PERMISSIONS_YAML)
    assert "push_branch" not in load_tools_config(TOOLS_YAML).tools["github_mcp"].operations

    for agent_id in permissions.agent_ids():
        result = decide(
            permissions, agent_id=agent_id, tool="github_mcp", operation="push_branch"
        )
        assert result.decision is PermissionDecision.DENY
        assert result.source == "default-deny"


def test_no_unattended_write_exists_anywhere_in_the_matrix() -> None:
    """The W2R2 tripwire, carried across the re-landing and now MEANINGFUL: the
    tool is configured, three operations are granted, two of them are
    `read_only: false` — and the set of `allow` grants on a write is still empty,
    because both writes are `ask_user`.

    ADR-030 §4's one ruled exception (`developer.github_mcp.push_branch: allow`)
    returns only with the engine-enablement ADR. Any `allow` on a write arriving
    before that trips here instead of arriving quietly.
    """
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


def test_the_composition_did_not_widen_what_an_approval_binds_to() -> None:
    """`merge_main` became two server calls; it did NOT become two approvals or
    four arguments. The `args_hash` still covers exactly these three fields, the
    PR number is derived state inside the approved execution, and the harness
    double every Stream F test runs against stays pinned to the same shape."""
    block = load_tools_config(TOOLS_YAML).tools["github_mcp"]
    merge_main = block.operations["merge_main"]

    assert merge_main.server_tools == ("create_pull_request", "merge_pull_request")
    assert merge_main.composition == "merge_via_pull_request"
    assert merge_main.params_model is MergeMainParams
    # Nothing a plan sends can name a pull request.
    assert set(MergeMainParams.model_fields) == EXPECTED_FIELDS

    for model, pin in (
        (PushBranchParams, harness.PushBranchParams),
        (MergeMainParams, harness.MergeMainParams),
    ):
        assert model.model_config.get("extra") == "forbid"
        assert set(model.model_fields) == EXPECTED_FIELDS
        assert set(model.model_fields) == set(pin.model_fields)


def test_the_developer_planning_grants_are_exactly_the_ruled_pair() -> None:
    """`config/agents.yaml` keeps both planning grants. `push_branch` is inert —
    layer 4 checks the adapter-built catalogue first and the plan-schema enum is
    catalogue-built, so a plan naming it is rejected before any permission
    decision (R1's grounds). A THIRD grant, or a grant on another tool, still
    trips this before it can pass unreviewed."""
    agents = yaml.safe_load(AGENTS_YAML.read_text("utf-8"))["agents"]

    assert agents["developer"]["tools"] == {
        "github_mcp": ["push_branch", "merge_main"]
    }
