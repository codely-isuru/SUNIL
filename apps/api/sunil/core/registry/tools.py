"""`config/tools.yaml` — the Tool Registry (FR-100): every tool and the
operations it exposes, by name.

This is the config-level inventory used for (a) startup cross-validation —
every `permissions.yaml` grant and every `agents.yaml` tool declaration
must name a real tool/operation here — and (b) building the plan schema's
`tools`/`action` enums (T9, `ARCHITECTURE_V1.md` §6.1 Layer 1). The
authoritative parameter *validation* is the Pydantic `params_model` T8
attaches to each `ToolOperation` in code (§9.3, §26.8); `params` below is a
cross-validated, human-readable inventory of what an operation accepts,
not a second enforcement mechanism.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from sunil.core.registry._yaml import read_yaml
from sunil.core.registry.errors import RegistrySchemaError, UnknownOperationError, UnknownToolError


class ToolOperationDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    read_only: bool
    description: str
    timeout_s: float
    params: dict[str, Any] = {}


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    display_name: str
    operations: dict[str, ToolOperationDefinition]


class ToolRegistry:
    def __init__(self, tools: dict[str, ToolDefinition]) -> None:
        self._tools = tools

    def get_tool(self, tool: str) -> ToolDefinition:
        try:
            return self._tools[tool]
        except KeyError:
            raise UnknownToolError(tool) from None

    def get_operation(self, tool: str, operation: str) -> ToolOperationDefinition:
        tool_def = self.get_tool(tool)
        try:
            return tool_def.operations[operation]
        except KeyError:
            raise UnknownOperationError(tool, operation) from None

    def has_operation(self, tool: str, operation: str) -> bool:
        return tool in self._tools and operation in self._tools[tool].operations

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


def load_tools(config_dir: Path) -> ToolRegistry:
    path = config_dir / "tools.yaml"
    raw = read_yaml(path)

    version = raw.get("version")
    if version != 1:
        raise RegistrySchemaError(f"{path}: expected version: 1, found {version!r}")

    tools_raw = raw.get("tools") or {}
    if not isinstance(tools_raw, dict):
        raise RegistrySchemaError(f"{path}: 'tools' must be a mapping")

    tools: dict[str, ToolDefinition] = {}
    for tool_name, body in tools_raw.items():
        body = body or {}
        operations_raw = body.get("operations") or {}
        if not isinstance(operations_raw, dict):
            raise RegistrySchemaError(f"{path}: {tool_name}.operations must be a mapping")

        operations: dict[str, ToolOperationDefinition] = {}
        for op_name, op_body in operations_raw.items():
            try:
                operations[op_name] = ToolOperationDefinition(name=op_name, **(op_body or {}))
            except Exception as exc:
                raise RegistrySchemaError(
                    f"{path}: {tool_name}.{op_name} is invalid: {exc}"
                ) from exc

        try:
            tools[tool_name] = ToolDefinition(
                name=tool_name,
                display_name=body.get("display_name", tool_name),
                operations=operations,
            )
        except Exception as exc:
            raise RegistrySchemaError(f"{path}: tool {tool_name!r} is invalid: {exc}") from exc

    if not tools:
        raise RegistrySchemaError(f"{path}: no tools defined")

    return ToolRegistry(tools)
