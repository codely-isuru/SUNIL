"""`sunil.core.registry.projects` — the static project mapping (FR-107,
ADR-000 Q7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sunil.core.registry.errors import RegistrySchemaError, UnknownProjectError
from sunil.core.registry.projects import UNKNOWN_PROJECT_KEY, load_projects

from .registry_helpers import valid_config_files, write_config_dir


def test_loads_easy_clean_workforce_from_config_only(valid_config_dir: Path) -> None:
    """ADR-000 Q7: `codely-isuru/easy_clean_workforce` must come from this
    file, not from a Python literal anywhere."""
    registry = load_projects(valid_config_dir)

    project = registry.get("easy_clean_workforce")

    assert project.display_name == "EasyClean Workforce"
    assert project.github.owner == "codely-isuru"
    assert project.github.repo == "easy_clean_workforce"


def test_unknown_project_raises_a_named_error_not_a_keyerror(valid_config_dir: Path) -> None:
    registry = load_projects(valid_config_dir)

    with pytest.raises(UnknownProjectError):
        registry.get("some_other_project")


def test_known_projects_matches_the_frozen_contract_shape(valid_config_dir: Path) -> None:
    """§11.3: `failure.known_projects: [{key, display_name}]`."""
    registry = load_projects(valid_config_dir)

    assert registry.known_projects() == [
        {"key": "easy_clean_workforce", "display_name": "EasyClean Workforce"}
    ]


def test_the_unknown_sentinel_may_never_be_configured_as_a_real_project(tmp_path: Path) -> None:
    files = valid_config_files()
    files["projects.yaml"]["projects"][UNKNOWN_PROJECT_KEY] = {
        "display_name": "Should never load",
        "github": {"owner": "x", "repo": "y"},
    }
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_projects(tmp_path)


def test_empty_projects_block_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    files["projects.yaml"]["projects"] = {}
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_projects(tmp_path)
