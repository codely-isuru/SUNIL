"""``config/permissions.yaml`` — the grants :mod:`sunil.core.permissions.engine`
reads (C1 §2.2, ADR-034 decision 2: "SUNIL config is the authority").

This module only loads and shapes the file. The three-valued ``decide()``
stays pure and file-free on purpose, so its default-deny proof needs no YAML.

Fail closed and LOUD: an unreadable file, a wrong ``version:``, a malformed
level or an invalid decision value raises :class:`PermissionsConfigError`
rather than yielding a partially-loaded grant tree. A half-loaded permission
file is worse than none — the operator believes a grant exists (or believes one
was removed) and the engine silently disagrees.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

_ALLOWED_DECISIONS = ("allow", "deny", "ask_user")


class PermissionsConfigError(Exception):
    """``config/permissions.yaml`` could not be loaded as specified."""


class PermissionRegistry:
    """``grant_for(agent, tool, operation)`` →
    ``"allow" | "deny" | "ask_user" | None``.

    Deliberately never raises and never defaults to a grant on a missing entry —
    returning ``None`` and letting the engine treat that as DENY is the engine's
    job (its own control flow), not this loader's.
    """

    def __init__(self, grants: dict[str, dict[str, dict[str, str]]]) -> None:
        self._grants = grants

    def grant_for(self, agent_id: str, tool: str, operation: str) -> str | None:
        return self._grants.get(agent_id, {}).get(tool, {}).get(operation)

    def agent_ids(self) -> list[str]:
        return list(self._grants)

    def referenced_tool_operations(self) -> set[tuple[str, str]]:
        """Every ``(tool, operation)`` pair named anywhere in the file — startup
        cross-validation checks each against ``config/tools.yaml`` (ADR-034: a
        granted operation that no configured tool exposes is a config bug, not a
        runtime surprise)."""
        pairs: set[tuple[str, str]] = set()
        for tools in self._grants.values():
            for tool, operations in tools.items():
                pairs.update((tool, operation) for operation in operations)
        return pairs


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # noqa: PLC0415 - kept lazy: the loader is the only yaml user
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise PermissionsConfigError(
            "PyYAML is required to load config/permissions.yaml"
        ) from exc

    if not path.is_file():
        raise PermissionsConfigError(f"{path}: permissions config not found")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PermissionsConfigError(f"{path}: not valid YAML ({exc})") from exc
    if not isinstance(raw, dict):
        raise PermissionsConfigError(f"{path}: top level must be a mapping")
    return raw


def load_permissions(path: Path | str) -> PermissionRegistry:
    """Load a ``permissions.yaml`` FILE path (not a directory).

    A file path rather than M1's ``config_dir``: this lane takes every config
    location as an explicit constructor/parameter value, so nothing here has to
    know where ``SUNIL_CONFIG_DIR`` points — the spine's wiring resolves that
    once and hands the path down.
    """
    path = Path(path)
    raw = _read_yaml(path)

    version = raw.get("version")
    if version != 1:
        raise PermissionsConfigError(f"{path}: expected version: 1, found {version!r}")

    agents_raw = raw.get("agents")
    if agents_raw is None:
        agents_raw = {}
    # `or {}` would be wrong here: an `agents: []` typo is falsy, and coercing it
    # to an empty mapping would load a file the operator believes grants things
    # as a silent deny-everything.
    if not isinstance(agents_raw, dict):
        raise PermissionsConfigError(f"{path}: 'agents' must be a mapping")

    grants: dict[str, dict[str, dict[str, str]]] = {}
    for agent_id, tools in agents_raw.items():
        if not isinstance(tools, dict):
            raise PermissionsConfigError(
                f"{path}: agent {agent_id!r} entry must be a mapping of tool -> operations"
            )
        grants[agent_id] = {}
        for tool, operations in tools.items():
            if not isinstance(operations, dict):
                raise PermissionsConfigError(
                    f"{path}: {agent_id}.{tool} must map operation -> decision"
                )
            grants[agent_id][tool] = {}
            for operation, decision in operations.items():
                if decision not in _ALLOWED_DECISIONS:
                    raise PermissionsConfigError(
                        f"{path}: {agent_id}.{tool}.{operation} has an invalid decision "
                        f"{decision!r} (must be one of {sorted(_ALLOWED_DECISIONS)})"
                    )
                grants[agent_id][tool][operation] = decision

    return PermissionRegistry(grants)
