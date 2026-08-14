"""`sunil.core.registry.tools` — the Tool Registry (FR-100)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sunil.core.registry.errors import RegistrySchemaError, UnknownOperationError, UnknownToolError
from sunil.core.registry.tools import load_tools

from .conftest import valid_config_files, write_config_dir


def test_loads_the_github_tool_and_its_operation(valid_config_dir: Path) -> None:
    registry = load_tools(valid_config_dir)

    operation = registry.get_operation("github", "list_recent_activity")

    assert operation.read_only is True
    assert operation.timeout_s == 15
    assert operation.params == {"project_key": {"type": "string", "required": True}}


def test_has_operation_is_true_for_a_real_tool_and_operation(valid_config_dir: Path) -> None:
    registry = load_tools(valid_config_dir)

    assert registry.has_operation("github", "list_recent_activity") is True
    assert registry.has_operation("github", "delete_repo") is False
    assert registry.has_operation("no_such_tool", "anything") is False


def test_unknown_tool_raises_a_named_error_not_a_keyerror(valid_config_dir: Path) -> None:
    registry = load_tools(valid_config_dir)

    with pytest.raises(UnknownToolError):
        registry.get_tool("no_such_tool")


def test_unknown_operation_on_a_real_tool_raises_a_named_error(valid_config_dir: Path) -> None:
    registry = load_tools(valid_config_dir)

    with pytest.raises(UnknownOperationError):
        registry.get_operation("github", "delete_repo")


def test_empty_tools_block_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    files["tools.yaml"]["tools"] = {}
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_tools(tmp_path)
