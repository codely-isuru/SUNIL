"""The `config/{agents,projects}.yaml` loaders.

Fail-closed and at boot: a missing file, a malformed mapping or an agent whose
`tools:` block is not `{tool: [operation, …]}` raises `RegistryError` from
`load_registries()`, which runs inside the app's lifespan. An app that booted
with a half-understood permission-adjacent config is worse than one that did not
boot.

`agents.yaml` is a **grant** file, not a capability list: `tools:` names the
operations an agent may plan. The plan validator checks it (layer 4) and the
permission engine checks `permissions.yaml` independently at the C1 chokepoint —
two different questions ("may this agent plan it" / "may this call proceed, and
does it need a human"), deliberately not collapsed into one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class RegistryError(Exception):
    """A `config/*.yaml` file is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True)
class AgentDefinition:
    id: str
    role: str
    preferred_capability: str
    #: `{tool_name: (operation, …)}` — the operations this agent may plan.
    tools: dict[str, tuple[str, ...]] = field(default_factory=dict)
    system_prompt: str = ""

    def get(self, key: str, default: Any = None) -> Any:
        """Mapping-style read, so the plan validator can treat a loaded
        definition and a plain test dict identically."""
        return getattr(self, key, default)


@dataclass(frozen=True)
class ProjectDefinition:
    key: str
    display_name: str
    description: str = ""


@dataclass(frozen=True)
class Registries:
    agents: dict[str, AgentDefinition]
    projects: dict[str, ProjectDefinition]


def load_registries(config_dir: str | Path) -> Registries:
    """Load and cross-validate every config file the spine owns."""
    directory = Path(config_dir)
    agents = _load_agents(directory / "agents.yaml")
    projects = _load_projects(directory / "projects.yaml")
    return Registries(agents=agents, projects=projects)


def _read_mapping(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RegistryError(f"config file not found: {path}")
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegistryError(f"{path.name} is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise RegistryError(f"{path.name} must be a mapping at the top level")
    return loaded


def _load_agents(path: Path) -> dict[str, AgentDefinition]:
    raw = _read_mapping(path).get("agents")
    if not isinstance(raw, dict) or not raw:
        raise RegistryError(f"{path.name} must define a non-empty `agents:` mapping")

    agents: dict[str, AgentDefinition] = {}
    for agent_id, body in raw.items():
        if not isinstance(body, dict):
            raise RegistryError(f"{path.name}: agent {agent_id!r} must be a mapping")
        tools_raw = body.get("tools", {}) or {}
        if not isinstance(tools_raw, dict):
            raise RegistryError(
                f"{path.name}: agent {agent_id!r} `tools:` must be a mapping of "
                "tool -> [operation, ...]"
            )
        tools: dict[str, tuple[str, ...]] = {}
        for tool, operations in tools_raw.items():
            if not isinstance(operations, list) or not all(
                isinstance(operation, str) for operation in operations
            ):
                raise RegistryError(
                    f"{path.name}: agent {agent_id!r} tool {tool!r} must list operation names"
                )
            tools[tool] = tuple(operations)
        agents[agent_id] = AgentDefinition(
            id=agent_id,
            role=str(body.get("role", agent_id)),
            preferred_capability=str(body.get("preferred_capability", "general_reasoning")),
            tools=tools,
            system_prompt=str(body.get("system_prompt", "")),
        )
    return agents


def _load_projects(path: Path) -> dict[str, ProjectDefinition]:
    raw = _read_mapping(path).get("projects")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise RegistryError(f"{path.name} `projects:` must be a mapping")

    projects: dict[str, ProjectDefinition] = {}
    for key, body in raw.items():
        body = body or {}
        if not isinstance(body, dict):
            raise RegistryError(f"{path.name}: project {key!r} must be a mapping")
        projects[key] = ProjectDefinition(
            key=key,
            display_name=str(body.get("display_name", key)),
            description=str(body.get("description", "")),
        )
    return projects
