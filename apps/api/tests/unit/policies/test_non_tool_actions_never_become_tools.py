"""Non-tool actions must never become tools — the catalogue-WIDE scan.

**QA finding F-1 (MEDIUM), re-landed by the w2r3 parcel.** This scan used to live
inside `tests/unit/agents/test_developer_mount.py`. Ruling R16's replacement of
that module dropped it, and its surviving fragment was vacuous against a dormant
tool: "no `github_mcp` operation is called `fix_and_pr`" is trivially true of a
tool with no operations at all. It is a **standalone module now, on purpose**, so
it survives the next rewrite of any mount module — which is the failure mode that
produced the finding.

## What it protects

The chokepoint governs **actions on the world**. Some things an agent does are
not that, and modelling one of them as a tool would create a governed surface
with no adapter behind it — a permission row, an approval card and an audit trail
for something that never reaches an external system, and therefore a decision the
owner was asked to make about nothing.

The named case is `fix_and_pr` (`docs/tasks/S2-F-openhands.md` §2): delegating a
work order to the sandboxed OpenHands engine. A sandboxed run that touches nothing
outside its own container is not an action on the world; the git writes the run
WANTS are expressed afterwards as ordinary tool calls (`merge_main`), decided like
anyone else's. `config/permissions.yaml` says this in prose. This module is what
makes it enforceable.

The scan is deliberately **whole-catalogue and whole-matrix**: it does not ask
"does `github_mcp` expose `fix_and_pr`", it asks "does ANY tool, anywhere, expose
it, and does ANY agent hold a grant for it". A future MCP server advertising a
tool of that name, or a new native adapter, trips here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from sunil.core.permissions.registry import load_permissions
from sunil.core.tool_framework.tools_config import load_tools_config

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOLS_YAML = REPO_ROOT / "config" / "tools.yaml"
PERMISSIONS_YAML = REPO_ROOT / "config" / "permissions.yaml"
AGENTS_YAML = REPO_ROOT / "config" / "agents.yaml"

#: Every action that is deliberately NOT a tool, with the ruling that says so.
#: A new entry here is a new invariant; removing one is a decision that needs an
#: ADR, because it means something that was not an action on the world now is.
NON_TOOL_ACTIONS: dict[str, str] = {
    "fix_and_pr": (
        "the developer's delegation to the sandboxed OpenHands engine — a "
        "NON-tool plan step addressed to the agent (docs/tasks/S2-F-openhands.md "
        "§2, and config/permissions.yaml's own comment). A sandboxed run that "
        "touches nothing outside its container is not an action on the world"
    ),
}


def _configured_operations() -> set[str]:
    return {
        operation
        for block in load_tools_config(TOOLS_YAML).tools.values()
        for operation in block.operations
    }


def _granted_operations() -> set[str]:
    return {
        operation
        for _tool, operation in load_permissions(PERMISSIONS_YAML).referenced_tool_operations()
    }


def test_the_scan_is_not_vacuous() -> None:
    """The guard on the guard. F-1 was a MEDIUM precisely because the surviving
    pin was true of an EMPTY catalogue, so it would have kept passing while the
    thing it protected rotted. If there is nothing to scan, this module is
    telling you nothing — say so loudly."""
    assert _configured_operations(), "the catalogue is empty — this scan proves nothing"
    assert _granted_operations(), "the permission matrix is empty — this scan proves nothing"


@pytest.mark.parametrize("action", sorted(NON_TOOL_ACTIONS))
def test_no_tool_in_the_whole_catalogue_exposes_it(action: str) -> None:
    """Whole-catalogue, not per-tool: a NEW server or native adapter advertising
    this name trips here, not only the one tool the finding was written about."""
    assert action not in _configured_operations(), NON_TOOL_ACTIONS[action]


@pytest.mark.parametrize("action", sorted(NON_TOOL_ACTIONS))
def test_no_agent_in_the_whole_matrix_holds_a_grant_for_it(action: str) -> None:
    """A grant would fail startup cross-validation anyway — but it would fail as
    "unknown operation", which reads like a typo. This says what it really is."""
    assert action not in _granted_operations(), NON_TOOL_ACTIONS[action]


@pytest.mark.parametrize("action", sorted(NON_TOOL_ACTIONS))
def test_no_agents_yaml_planning_grant_names_it(action: str) -> None:
    """The third file, and the one nothing else cross-validates: `agents.yaml`'s
    planning grants are checked against the adapter-built CATALOGUE at layer 4,
    not against `tools.yaml` at startup — so a planning grant for a non-tool
    action would sit in the tree unexamined until a plan named it."""
    agents = yaml.safe_load(AGENTS_YAML.read_text("utf-8"))["agents"]

    for agent_id, spec in agents.items():
        for tool, operations in (spec.get("tools") or {}).items():
            assert action not in (operations or []), (
                f"{agent_id}.{tool} plans for {action!r}: {NON_TOOL_ACTIONS[action]}"
            )


#: Planning grants in `config/agents.yaml` that name an operation
#: `config/tools.yaml` does not configure — each one RULED, each one structurally
#: inert on R1's grounds (layer 4 checks the adapter-built catalogue first, and
#: the plan-schema enum is catalogue-built, so a plan naming one is rejected
#: before any permission decision). Named individually so each is a decision
#: rather than a hole.
RULED_INERT_PLANNING_GRANTS: dict[str, str] = {
    "project_manager.fake_tool.echo": "wave-1 ruling R1 — the C1 §6.3 fake tool",
    "project_manager.fake_tool.write_item": "wave-1 ruling R1 — the C1 §6.3 fake tool",
    "developer.github_mcp.push_branch": (
        "ruling R16 part 4 — the operation's executor belongs to the "
        "engine-enablement ADR, which has not landed; parcel step 5 forbade this "
        "parcel inventing one"
    ),
}


def test_every_planning_grant_names_a_configured_operation_or_a_ruled_dormancy() -> None:
    """The other half of the same gap. `config/agents.yaml` is NOT cross-
    validated against `config/tools.yaml` at startup, so a planning grant naming
    an operation nothing exposes fails at request time and looks like the planner
    hallucinated it.

    Three such grants exist today and every one is ruled (see
    `RULED_INERT_PLANNING_GRANTS`). Any OTHER unconfigured planning grant trips
    this — and so does a ruled one becoming configured without its entry being
    removed, which is how a dormancy quietly stops being one.
    """
    agents = yaml.safe_load(AGENTS_YAML.read_text("utf-8"))["agents"]
    configured = load_tools_config(TOOLS_YAML).tools

    dangling = {
        f"{agent_id}.{tool}.{operation}"
        for agent_id, spec in agents.items()
        for tool, operations in (spec.get("tools") or {}).items()
        for operation in (operations or [])
        if tool not in configured or operation not in configured[tool].operations
    }

    assert dangling == set(RULED_INERT_PLANNING_GRANTS)
