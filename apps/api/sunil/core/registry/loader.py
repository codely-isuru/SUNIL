"""Load every `config/*.yaml` registry and cross-validate them as one unit
(`docs/M1_BUILD_PLAN.md` T3 "startup cross-validation"; ADR-016 §10.2).

`load_registries()` is the single function `sunil.main.create_app()`'s
startup should call: it raises a `RegistryError` — never lets a caller
reach a half-loaded or internally-inconsistent set of registries — so the
app refuses to boot on a bad edit, exactly as ADR-016 requires ("that
refusal is the control that makes a bad edit loud and immediate").
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sunil.core.registry.agents import AgentRegistry, load_agents
from sunil.core.registry.capture import CaptureRegistry, load_capture
from sunil.core.registry.errors import RegistryCrossValidationError
from sunil.core.registry.model_catalogue import ModelRegistry, load_models
from sunil.core.registry.paths import resolve_config_dir
from sunil.core.registry.permissions import PermissionRegistry, load_permissions
from sunil.core.registry.projects import ProjectRegistry, load_projects
from sunil.core.registry.tools import ToolRegistry, load_tools


@dataclass(frozen=True)
class Registries:
    """Every config registry, loaded and cross-validated together. One
    instance is built at startup and threaded to whatever needs it — T6's
    router, T7's permission engine, T8's tool manager, T9's plan schema
    builder, T10's agent runner. Nobody re-reads a YAML file after startup
    (ADR-016 §4: restart-on-change, no hot reload)."""

    agents: AgentRegistry
    permissions: PermissionRegistry
    projects: ProjectRegistry
    models: ModelRegistry
    tools: ToolRegistry
    capture: CaptureRegistry


def load_registries(config_dir: str | Path) -> Registries:
    """Load all six files from `config_dir` and cross-validate them.

    `config_dir` is normally `Settings.sunil_config_dir`
    (`SUNIL_CONFIG_DIR`, ADR-016) and is resolved with
    `paths.resolve_config_dir` first.

    Raises `RegistryFileError` / `RegistrySchemaError` on a single bad
    file, and `RegistryCrossValidationError` — carrying every mismatch
    found, not just the first — when the files are each individually
    valid but disagree with one another.
    """
    resolved = resolve_config_dir(config_dir)

    registries = Registries(
        agents=load_agents(resolved),
        permissions=load_permissions(resolved),
        projects=load_projects(resolved),
        models=load_models(resolved),
        tools=load_tools(resolved),
        capture=load_capture(resolved),
    )
    validate_cross_references(registries)
    return registries


def validate_cross_references(registries: Registries) -> None:
    """The cross-checks `docs/M1_BUILD_PLAN.md` T3 names — every agent in
    `permissions.yaml` exists in `agents.yaml`, every tool/operation
    referenced exists in `tools.yaml`, every project referenced in
    `capture.yaml` exists in `projects.yaml` — plus one more in the same
    spirit: an agent's own tool grants in `agents.yaml` must name real
    tools/operations too. Every problem found is collected before raising,
    so one fix-and-restart cycle surfaces all of them at once.
    """
    problems: list[str] = []

    # 1. every agent in permissions.yaml exists in agents.yaml
    for agent_id in registries.permissions.agent_ids():
        if agent_id not in registries.agents:
            problems.append(
                f"permissions.yaml grants agent {agent_id!r}, which is not defined in agents.yaml"
            )

    # 2. every tool/operation permissions.yaml references exists in tools.yaml
    for tool, operation in registries.permissions.referenced_tool_operations():
        if not registries.tools.has_operation(tool, operation):
            problems.append(
                f"permissions.yaml references {tool}.{operation}, "
                "which is not defined in tools.yaml"
            )

    # 2b. every tool/operation an agent declares in agents.yaml exists in tools.yaml too
    for agent in registries.agents.values():
        for tool, operations in agent.tools.items():
            for operation in operations:
                if not registries.tools.has_operation(tool, operation):
                    problems.append(
                        f"agents.yaml agent {agent.id!r} declares {tool}.{operation}, "
                        "which is not defined in tools.yaml"
                    )

    # 3. every project referenced in capture.yaml exists in projects.yaml
    for project_key in registries.capture.referenced_project_keys():
        if project_key not in registries.projects:
            problems.append(
                f"capture.yaml overrides project {project_key!r}, "
                "which is not defined in projects.yaml"
            )

    if problems:
        raise RegistryCrossValidationError(problems)
