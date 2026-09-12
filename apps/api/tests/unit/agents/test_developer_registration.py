"""`config/agents.yaml` must actually register the developer agent.

An agent that exists in code and not in the registry is unreachable: the plan
validator rejects every plan naming it (layer 4), and the schema builder never
offers it as a choice (layer 1). This is the cheap test that catches "built but
never mounted" — the failure mode ADR-016's mounted-config policy makes possible
by design.
"""

from __future__ import annotations

from pathlib import Path

from sunil.agents.developer.agent import GIT_TOOL, GOVERNED_OPERATIONS, DeveloperAgent
from sunil.core.registry.loader import load_registries

#: tests/unit/agents/<this file> -> tests/unit -> tests -> apps/api -> apps -> repo root
CONFIG_DIR = Path(__file__).resolve().parents[5] / "config"


def test_the_developer_agent_is_registered_with_exactly_its_git_grants():
    agents = load_registries(CONFIG_DIR).agents

    assert DeveloperAgent.id in agents, "config/agents.yaml does not mount `developer`"
    developer = agents[DeveloperAgent.id]

    # The grant list is a PLANNING grant, not an execution authority: whether a
    # call proceeds is decided independently at the C1 chokepoint from
    # config/permissions.yaml. Both files must name the same operations, or the
    # agent can plan a call it can never make.
    assert set(developer.tools[GIT_TOOL]) == set(GOVERNED_OPERATIONS)

    # Nothing else. A developer agent that could plan `n8n_mcp.run_workflow`
    # because someone widened this file is exactly the drift this asserts away.
    assert set(developer.tools) == {GIT_TOOL}


def test_the_registry_still_mounts_the_project_manager():
    """The developer agent is additive: Stream F must not have disturbed the
    spine's own agent."""
    agents = load_registries(CONFIG_DIR).agents
    assert "project_manager" in agents
