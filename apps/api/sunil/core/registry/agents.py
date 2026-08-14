"""`config/agents.yaml` — the Agent Registry (FR-080, FR-084).

Agent role, instructions, objectives, memory scope, tool grants and model
capability preference are data, not code (`ARCHITECTURE_V1.md` §10.2, §7.3
"agents is deliberately not a table") — this loader is the only place that
reads the file, so an agent's behaviour changes with a config edit and a
restart, never a code deployment (FR-084).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from sunil.core.registry._yaml import read_yaml
from sunil.core.registry.errors import RegistrySchemaError, UnknownAgentError


class AgentDefinition(BaseModel):
    """One agent's full configuration (§10.2 shape). `extra="forbid"`
    catches a typo'd key at load time rather than silently ignoring it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    role: str
    instructions: list[str]
    objectives: list[str]
    memory_scope: list[str]
    preferred_capability: str
    escalation_capability: str
    # tool name -> operations this agent may request (FR-082's own grant
    # list, checked by the agent runner before the Tool Manager).
    tools: dict[str, list[str]] = {}


class AgentRegistry:
    """Queryable view over `config/agents.yaml`."""

    def __init__(self, agents: dict[str, AgentDefinition]) -> None:
        self._agents = agents

    def get(self, agent_id: str) -> AgentDefinition:
        try:
            return self._agents[agent_id]
        except KeyError:
            raise UnknownAgentError(agent_id) from None

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def keys(self) -> list[str]:
        return list(self._agents.keys())

    def values(self) -> list[AgentDefinition]:
        return list(self._agents.values())


def load_agents(config_dir: Path) -> AgentRegistry:
    path = config_dir / "agents.yaml"
    raw = read_yaml(path)

    version = raw.get("version")
    if version != 1:
        raise RegistrySchemaError(f"{path}: expected version: 1, found {version!r}")

    agents_raw = raw.get("agents") or {}
    if not isinstance(agents_raw, dict):
        raise RegistrySchemaError(f"{path}: 'agents' must be a mapping")

    agents: dict[str, AgentDefinition] = {}
    for agent_id, body in agents_raw.items():
        try:
            agents[agent_id] = AgentDefinition(id=agent_id, **(body or {}))
        except Exception as exc:
            raise RegistrySchemaError(f"{path}: agent {agent_id!r} is invalid: {exc}") from exc

    if not agents:
        raise RegistrySchemaError(f"{path}: no agents defined")

    return AgentRegistry(agents)
