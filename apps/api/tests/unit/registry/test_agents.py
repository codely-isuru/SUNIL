"""`sunil.core.registry.agents` — the Agent Registry (FR-080, FR-084)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sunil.core.registry.agents import load_agents
from sunil.core.registry.errors import RegistryFileError, RegistrySchemaError, UnknownAgentError

from .conftest import valid_config_files, write_config_dir


def test_loads_the_project_manager_agent_with_the_full_10_2_shape(valid_config_dir: Path) -> None:
    registry = load_agents(valid_config_dir)

    agent = registry.get("project_manager")

    assert agent.role == "Manage software projects and identify risks."
    assert agent.instructions == ["Review recent project activity."]
    assert agent.objectives == ["Report current project status."]
    assert agent.memory_scope == ["short_term"]
    assert agent.preferred_capability == "general_reasoning"
    assert agent.escalation_capability == "complex_reasoning"
    assert agent.tools == {"github": ["list_recent_activity"]}


def test_unknown_agent_raises_a_named_error_not_a_keyerror(valid_config_dir: Path) -> None:
    registry = load_agents(valid_config_dir)

    with pytest.raises(UnknownAgentError):
        registry.get("no_such_agent")


def test_membership_check_does_not_raise(valid_config_dir: Path) -> None:
    registry = load_agents(valid_config_dir)

    assert "project_manager" in registry
    assert "no_such_agent" not in registry


def test_missing_file_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(RegistryFileError):
        load_agents(tmp_path)


def test_extra_unknown_key_is_rejected(tmp_path: Path) -> None:
    files = valid_config_files()
    files["agents.yaml"]["agents"]["project_manager"]["not_a_real_field"] = "oops"
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_agents(tmp_path)


def test_empty_agents_block_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    files["agents.yaml"]["agents"] = {}
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_agents(tmp_path)


def test_wrong_version_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    files["agents.yaml"]["version"] = 2
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_agents(tmp_path)
