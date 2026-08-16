"""`config/projects.yaml` — the static project-name-to-repository mapping
(FR-107, ADR-000 Q7).

The M1 target repository's owner/repo coordinates live in that YAML file
and only there — no `.py` module anywhere in this package may name them
as a literal (`docs/M1_BUILD_PLAN.md` T3 "Watch"; `THREAT_MODEL.md` T-16;
Security's `test_the_target_repository_is_never_hard_coded` greps this
whole package for exactly that string, so this docstring deliberately
does not repeat it either). The tool adapter (T8) resolves a plan's
`project_key` through `ProjectRegistry.get` and never accepts owner/repo
from the model.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from sunil.core.registry._yaml import read_yaml
from sunil.core.registry.errors import RegistrySchemaError, UnknownProjectError

# The plan schema's project-not-recognised sentinel (§6.1's
# `project_key: "__unknown__"`). Never a real project key.
UNKNOWN_PROJECT_KEY = "__unknown__"


class GithubCoordinates(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    owner: str
    repo: str


class ProjectDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    display_name: str
    github: GithubCoordinates


class ProjectRegistry:
    def __init__(self, projects: dict[str, ProjectDefinition]) -> None:
        self._projects = projects

    def get(self, project_key: str) -> ProjectDefinition:
        try:
            return self._projects[project_key]
        except KeyError:
            raise UnknownProjectError(project_key) from None

    def __contains__(self, project_key: str) -> bool:
        return project_key in self._projects

    def keys(self) -> list[str]:
        return list(self._projects.keys())

    def known_projects(self) -> list[dict[str, str]]:
        """`[{key, display_name}]` — the exact shape the frozen §6
        contract's `failure.known_projects` needs
        (`ARCHITECTURE_V1.md` §11.3), sourced from config rather than a
        second hard-coded list."""
        return [{"key": p.key, "display_name": p.display_name} for p in self._projects.values()]


def load_projects(config_dir: Path) -> ProjectRegistry:
    path = config_dir / "projects.yaml"
    raw = read_yaml(path)

    version = raw.get("version")
    if version != 1:
        raise RegistrySchemaError(f"{path}: expected version: 1, found {version!r}")

    projects_raw = raw.get("projects") or {}
    if not isinstance(projects_raw, dict):
        raise RegistrySchemaError(f"{path}: 'projects' must be a mapping")

    projects: dict[str, ProjectDefinition] = {}
    for key, body in projects_raw.items():
        if key == UNKNOWN_PROJECT_KEY:
            raise RegistrySchemaError(
                f"{path}: {UNKNOWN_PROJECT_KEY!r} is the plan schema's reserved "
                "unknown-project sentinel and may never be a configured project"
            )
        try:
            projects[key] = ProjectDefinition(key=key, **(body or {}))
        except Exception as exc:
            raise RegistrySchemaError(f"{path}: project {key!r} is invalid: {exc}") from exc

    if not projects:
        raise RegistrySchemaError(f"{path}: no projects defined")

    return ProjectRegistry(projects)
