"""`sunil.core.registry.permissions` — permission grants (§9.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sunil.core.registry.errors import RegistrySchemaError
from sunil.core.registry.permissions import PermissionRegistry, load_permissions

from .conftest import valid_config_files, write_config_dir


def test_grant_for_returns_the_configured_decision(valid_config_dir: Path) -> None:
    registry = load_permissions(valid_config_dir)

    assert registry.grant_for("project_manager", "github", "list_recent_activity") == "allow"


def test_grant_for_returns_none_never_raises_on_a_missing_entry(valid_config_dir: Path) -> None:
    """Default-deny is `core/permissions/engine.py`'s job — this loader
    must not pre-empt it by raising or by guessing a decision."""
    registry = load_permissions(valid_config_dir)

    assert registry.grant_for("project_manager", "github", "delete_repo") is None
    assert registry.grant_for("no_such_agent", "github", "list_recent_activity") is None


def test_empty_permission_registry_denies_everything_by_returning_none() -> None:
    """Mirrors T7's own defining test — an empty grant map, no file
    involved at all, and every lookup comes back `None`."""
    registry = PermissionRegistry({})

    assert registry.grant_for("project_manager", "github", "list_recent_activity") is None


def test_referenced_tool_operations_collects_every_grant(valid_config_dir: Path) -> None:
    registry = load_permissions(valid_config_dir)

    assert registry.referenced_tool_operations() == {("github", "list_recent_activity")}


def test_invalid_decision_value_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    files["permissions.yaml"]["agents"]["project_manager"]["github"]["list_recent_activity"] = (
        "sure_why_not"
    )
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_permissions(tmp_path)


def test_ask_user_is_a_legal_value_even_though_m1_never_returns_it(tmp_path: Path) -> None:
    """FR-121: M1 contains no write/destructive operation so `ASK_USER` is
    never actually returned, but the value must be legal in config from
    day one so M5 adds a queue, not a new enum member."""
    files = valid_config_files()
    files["permissions.yaml"]["agents"]["project_manager"]["github"]["list_recent_activity"] = (
        "ask_user"
    )
    write_config_dir(tmp_path, files)

    registry = load_permissions(tmp_path)

    assert registry.grant_for("project_manager", "github", "list_recent_activity") == "ask_user"
