"""``config/tools.yaml`` — the tool registry the chokepoint is wired from.

ADR-034 fixes both the shape and the authority:

* shape — ``{server_id: {kind, command|base_url_env, version, credential_env,
  operations: {name: {read_only, timeout_s, params_ref}}}}``;
* authority — "an MCP tool is callable IFF it appears in ``config/tools.yaml``
  with an explicit ``operations:`` entry ... AND has a permission row. A
  server-advertised tool absent from config does not exist."

So this loader is not a convenience: it is the file that decides what exists.
Every malformed case therefore fails LOUD (:class:`ToolsConfigError`) instead of
loading a partial registry — a silently-dropped operation looks exactly like a
permission problem at the call site, hours from its cause.

This is the lane's own thin loader (the brief's constraint): it takes a file
path, imports nothing from ``sunil.settings`` and knows nothing about
``SUNIL_CONFIG_DIR``. Secret VALUES never appear here — ``credential_env`` and
``*_env`` entries are variable NAMES, resolved from ``Settings`` at spawn
(C1 §5).
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sunil.core.permissions.registry import PermissionRegistry
from sunil.core.tool_framework.base import AdapterKind
from sunil.tools.mcp.config import McpOperationConfig


class ToolsConfigError(Exception):
    """``config/tools.yaml`` could not be loaded as ADR-034 specifies."""


@dataclass(frozen=True)
class ToolBlock:
    """One tool: a native adapter or one MCP server (ADR-034: server = tool)."""

    server_id: str
    kind: AdapterKind
    display_name: str
    operations: dict[str, McpOperationConfig]
    command: list[str] | None = None
    version: str | None = None
    base_url_env: str | None = None
    auth_token_env: str | None = None
    credential_env: tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolsConfig:
    tools: dict[str, ToolBlock]


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # noqa: PLC0415 - the loader is the only yaml user
    except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
        raise ToolsConfigError("PyYAML is required to load config/tools.yaml") from exc
    if not path.is_file():
        raise ToolsConfigError(f"{path}: tools config not found")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ToolsConfigError(f"{path}: not valid YAML ({exc})") from exc
    if not isinstance(raw, dict):
        raise ToolsConfigError(f"{path}: top level must be a mapping")
    return raw


def _resolve_params_model(reference: Any, *, where: str) -> type[BaseModel]:
    """``"package.module:ClassName"`` → the Pydantic model.

    Refuses anything that is not a ``BaseModel`` subclass with
    ``extra="forbid"`` (C1 §2 / §26.8): the params model is what the
    ``args_hash`` is computed over, so a model that quietly accepts unknown keys
    would let a plan smuggle arguments past the value the approval binds to.
    """
    if not isinstance(reference, str) or ":" not in reference:
        raise ToolsConfigError(
            f"{where}: params_ref must be 'module:ClassName', found {reference!r}"
        )
    module_name, _, attribute = reference.partition(":")
    try:
        model = getattr(import_module(module_name), attribute)
    except (ImportError, AttributeError) as exc:
        raise ToolsConfigError(f"{where}: params_ref {reference!r} does not resolve ({exc})") from exc
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        raise ToolsConfigError(
            f"{where}: params_ref {reference!r} is not a Pydantic model"
        )
    if model.model_config.get("extra") != "forbid":
        raise ToolsConfigError(
            f'{where}: params_ref {reference!r} must set extra="forbid" (C1 §2)'
        )
    return model


def _operations(raw: Any, *, where: str) -> dict[str, McpOperationConfig]:
    if not isinstance(raw, dict) or not raw:
        raise ToolsConfigError(f"{where}: must declare operations (ADR-034)")
    operations: dict[str, McpOperationConfig] = {}
    for name, spec in raw.items():
        if not isinstance(spec, dict):
            raise ToolsConfigError(f"{where}.{name}: operation entry must be a mapping")
        read_only = spec.get("read_only")
        if not isinstance(read_only, bool):
            raise ToolsConfigError(
                f"{where}.{name}: read_only must be true or false — SUNIL's value, "
                "never the server's readOnlyHint (ADR-034 decision 3)"
            )
        timeout_s = spec.get("timeout_s")
        if not isinstance(timeout_s, (int, float)) or isinstance(timeout_s, bool) or timeout_s <= 0:
            raise ToolsConfigError(f"{where}.{name}: timeout_s must be a positive number")
        model = _resolve_params_model(spec.get("params_ref"), where=f"{where}.{name}")
        operations[name] = McpOperationConfig(
            name=name,
            params_model=model,
            read_only=read_only,
            timeout_s=float(timeout_s),
        )
    return operations


def load_tools_config(path: Path | str) -> ToolsConfig:
    path = Path(path)
    raw = _read_yaml(path)

    if raw.get("version") != 1:
        raise ToolsConfigError(f"{path}: expected version: 1, found {raw.get('version')!r}")
    tools_raw = raw.get("tools")
    if tools_raw is None:
        tools_raw = {}
    if not isinstance(tools_raw, dict):
        raise ToolsConfigError(f"{path}: 'tools' must be a mapping")

    tools: dict[str, ToolBlock] = {}
    for server_id, block in tools_raw.items():
        where = f"{path}:{server_id}"
        if not isinstance(block, dict):
            raise ToolsConfigError(f"{where}: tool entry must be a mapping")
        try:
            kind = AdapterKind(block.get("kind"))
        except ValueError as exc:
            raise ToolsConfigError(
                f"{where}: unknown kind {block.get('kind')!r} (expected one of "
                f"{[member.value for member in AdapterKind]})"
            ) from exc

        operations = _operations(block.get("operations"), where=where)
        command = block.get("command")
        credential_env = tuple(block.get("credential_env") or ())

        if kind is AdapterKind.MCP_STDIO:
            if not isinstance(command, list) or not command:
                raise ToolsConfigError(f"{where}: kind mcp_stdio requires a non-empty command")
            if not block.get("version"):
                raise ToolsConfigError(
                    f"{where}: kind mcp_stdio requires a pinned version (ADR-034: pinned "
                    "server versions, drift visible at startup)"
                )
        if kind is AdapterKind.MCP_HTTP and not block.get("base_url_env"):
            raise ToolsConfigError(
                f"{where}: kind mcp_http requires base_url_env — a Settings field name, so "
                "the ADR-033 host validator sees the URL (never a literal URL here)"
            )

        tools[server_id] = ToolBlock(
            server_id=server_id,
            kind=kind,
            display_name=str(block.get("display_name") or server_id),
            operations=operations,
            command=[str(part) for part in command] if isinstance(command, list) else None,
            version=str(block["version"]) if block.get("version") else None,
            base_url_env=block.get("base_url_env"),
            auth_token_env=block.get("auth_token_env"),
            credential_env=tuple(str(name) for name in credential_env),
        )

    return ToolsConfig(tools=tools)


def cross_validate_permissions(config: ToolsConfig, permissions: PermissionRegistry) -> None:
    """Every granted ``(tool, operation)`` must exist in ``config/tools.yaml``.

    M1's startup cross-validation, kept: a grant for a tool or operation nothing
    exposes is a config bug, and the only alternative to failing here is a
    default-deny at the call site that looks like a permission decision rather
    than a typo. ADR-034 relies on this pairing — "callable IFF configured AND
    granted" is only checkable if both halves are read together.
    """
    unknown: list[str] = []
    for tool, operation in sorted(permissions.referenced_tool_operations()):
        block = config.tools.get(tool)
        if block is None:
            unknown.append(f"{tool} (no such tool)")
        elif operation not in block.operations:
            unknown.append(f"{tool}.{operation} (tool exposes no such operation)")
    if unknown:
        raise ToolsConfigError(
            "config/permissions.yaml grants triples that config/tools.yaml does not "
            f"declare: {unknown}"
        )
