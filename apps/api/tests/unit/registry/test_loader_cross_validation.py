"""`sunil.core.registry.loader` — cross-validation across the six files
(`docs/M1_BUILD_PLAN.md` T3 "startup cross-validation"; ADR-016 §10.2:
"the process refuses to boot on a mismatch")."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import valid_config_files, write_config_dir
from sunil.core.registry.errors import RegistryCrossValidationError
from sunil.core.registry.loader import load_registries


def test_a_consistent_config_set_loads_with_no_error(valid_config_dir: Path) -> None:
    registries = load_registries(valid_config_dir)

    assert "project_manager" in registries.agents
    grant = registries.permissions.grant_for("project_manager", "github", "list_recent_activity")
    assert grant == "allow"
    assert registries.projects.get("easy_clean_workforce").github.repo == "easy_clean_workforce"
    assert registries.tools.has_operation("github", "list_recent_activity")
    assert registries.models.get_model("claude-sonnet-5") is not None


def test_permissions_agent_missing_from_agents_yaml_refuses_to_boot(tmp_path: Path) -> None:
    files = valid_config_files()
    files["permissions.yaml"]["agents"]["a_ghost_agent"] = {
        "github": {"list_recent_activity": "allow"}
    }
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistryCrossValidationError) as exc_info:
        load_registries(tmp_path)

    assert "a_ghost_agent" in str(exc_info.value)


def test_permissions_operation_missing_from_tools_yaml_refuses_to_boot(tmp_path: Path) -> None:
    files = valid_config_files()
    files["permissions.yaml"]["agents"]["project_manager"]["github"]["delete_repo"] = "deny"
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistryCrossValidationError) as exc_info:
        load_registries(tmp_path)

    assert "delete_repo" in str(exc_info.value)


def test_agent_tool_grant_missing_from_tools_yaml_refuses_to_boot(tmp_path: Path) -> None:
    files = valid_config_files()
    files["agents.yaml"]["agents"]["project_manager"]["tools"]["github"].append("delete_repo")
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistryCrossValidationError) as exc_info:
        load_registries(tmp_path)

    assert "delete_repo" in str(exc_info.value)


def test_capture_override_for_an_unregistered_project_refuses_to_boot(tmp_path: Path) -> None:
    files = valid_config_files()
    files["capture.yaml"]["project_overrides"]["a_project_nobody_configured"] = {
        "message": {
            "capture_policy": "metadata_only",
            "sensitivity": "confidential",
            "retention_class": "standard",
        }
    }
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistryCrossValidationError) as exc_info:
        load_registries(tmp_path)

    assert "a_project_nobody_configured" in str(exc_info.value)


def test_every_problem_is_collected_not_just_the_first(tmp_path: Path) -> None:
    """One fix-and-restart cycle should surface every mismatch, not one
    per restart."""
    files = valid_config_files()
    files["permissions.yaml"]["agents"]["a_ghost_agent"] = {
        "github": {"list_recent_activity": "allow"}
    }
    files["capture.yaml"]["project_overrides"]["a_project_nobody_configured"] = {
        "message": {
            "capture_policy": "metadata_only",
            "sensitivity": "confidential",
            "retention_class": "standard",
        }
    }
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistryCrossValidationError) as exc_info:
        load_registries(tmp_path)

    assert len(exc_info.value.problems) == 2
