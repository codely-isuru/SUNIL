"""`config/permissions.yaml` — the grants `core/permissions/engine.py`
(T7) reads (`ARCHITECTURE_V1.md` §9.2, FR-120/121).

This module only loads and shapes the file. The three-valued `decide()`
function stays pure and file-free on purpose: T7's own defining test,
`test_empty_permission_config_denies_everything`, constructs a
`PermissionRegistry` with an empty grant map directly, with no file on
disk at all.
"""

from __future__ import annotations

from pathlib import Path

from sunil.core.registry._yaml import read_yaml
from sunil.core.registry.errors import RegistrySchemaError

_ALLOWED_DECISIONS = {"allow", "deny", "ask_user"}


class PermissionRegistry:
    """`grant_for(agent, tool, operation)` -> `"allow"|"deny"|"ask_user"|None`.

    Deliberately never raises and never defaults to a grant on a missing
    entry — returning `None` and letting the caller treat that as DENY is
    `core/permissions/engine.py`'s job (§9.2: "the missing-key branch
    returns DENY"), not this loader's.
    """

    def __init__(self, grants: dict[str, dict[str, dict[str, str]]]) -> None:
        self._grants = grants

    def grant_for(self, agent_id: str, tool: str, operation: str) -> str | None:
        return self._grants.get(agent_id, {}).get(tool, {}).get(operation)

    def agent_ids(self) -> list[str]:
        return list(self._grants.keys())

    def referenced_tool_operations(self) -> set[tuple[str, str]]:
        """Every `(tool, operation)` pair named anywhere in the file —
        startup cross-validation checks each against `config/tools.yaml`."""
        pairs: set[tuple[str, str]] = set()
        for tools in self._grants.values():
            for tool, operations in tools.items():
                pairs.update((tool, operation) for operation in operations)
        return pairs


def load_permissions(config_dir: Path) -> PermissionRegistry:
    path = config_dir / "permissions.yaml"
    raw = read_yaml(path)

    version = raw.get("version")
    if version != 1:
        raise RegistrySchemaError(f"{path}: expected version: 1, found {version!r}")

    agents_raw = raw.get("agents") or {}
    if not isinstance(agents_raw, dict):
        raise RegistrySchemaError(f"{path}: 'agents' must be a mapping")

    grants: dict[str, dict[str, dict[str, str]]] = {}
    for agent_id, tools in agents_raw.items():
        if not isinstance(tools, dict):
            raise RegistrySchemaError(f"{path}: agent {agent_id!r} entry must be a mapping")
        grants[agent_id] = {}
        for tool, operations in tools.items():
            if not isinstance(operations, dict):
                raise RegistrySchemaError(
                    f"{path}: {agent_id}.{tool} must map operation -> decision"
                )
            grants[agent_id][tool] = {}
            for operation, decision in operations.items():
                if decision not in _ALLOWED_DECISIONS:
                    raise RegistrySchemaError(
                        f"{path}: {agent_id}.{tool}.{operation} has an invalid decision "
                        f"{decision!r} (must be one of {sorted(_ALLOWED_DECISIONS)})"
                    )
                grants[agent_id][tool][operation] = decision

    return PermissionRegistry(grants)
