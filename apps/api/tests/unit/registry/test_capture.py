"""`sunil.core.registry.capture` — training-data capture defaults (A-6,
ADR-014, §13.2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import valid_config_files, write_config_dir
from sunil.core.registry.capture import CaptureKind, load_capture
from sunil.core.registry.errors import RegistrySchemaError


def test_loads_the_default_for_every_content_kind(valid_config_dir: Path) -> None:
    registry = load_capture(valid_config_dir)

    for kind in CaptureKind:
        defaults = registry.defaults_for(kind)
        assert defaults.capture_policy == "redacted_full"
        assert defaults.sensitivity == "internal"

    # Memory is the one kind with shorter retention (§13.2 table).
    assert registry.defaults_for(CaptureKind.MEMORY).retention_class == "transient"
    assert registry.defaults_for(CaptureKind.MESSAGE).retention_class == "standard"


def test_project_override_takes_precedence_over_the_default(tmp_path: Path) -> None:
    files = valid_config_files()
    files["capture.yaml"]["project_overrides"]["easy_clean_workforce"] = {
        "message": {
            "capture_policy": "metadata_only",
            "sensitivity": "confidential",
            "retention_class": "standard",
        }
    }
    write_config_dir(tmp_path, files)

    registry = load_capture(tmp_path)

    overridden = registry.defaults_for(CaptureKind.MESSAGE, project_key="easy_clean_workforce")
    assert overridden.capture_policy == "metadata_only"
    assert overridden.sensitivity == "confidential"

    # A kind the override does not mention still falls back to the default.
    unaffected = registry.defaults_for(CaptureKind.PLAN, project_key="easy_clean_workforce")
    assert unaffected.capture_policy == "redacted_full"


def test_unconfigured_project_key_never_raises_just_uses_the_default(
    valid_config_dir: Path,
) -> None:
    registry = load_capture(valid_config_dir)

    defaults = registry.defaults_for(
        CaptureKind.MESSAGE, project_key="some_project_with_no_override"
    )

    assert defaults.capture_policy == "redacted_full"


def test_referenced_project_keys_reflects_the_overrides_block(tmp_path: Path) -> None:
    files = valid_config_files()
    files["capture.yaml"]["project_overrides"]["easy_clean_workforce"] = {
        "message": {
            "capture_policy": "metadata_only",
            "sensitivity": "confidential",
            "retention_class": "standard",
        }
    }
    write_config_dir(tmp_path, files)

    registry = load_capture(tmp_path)

    assert registry.referenced_project_keys() == {"easy_clean_workforce"}


def test_missing_default_for_a_content_kind_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    del files["capture.yaml"]["defaults"]["memory"]
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_capture(tmp_path)


def test_invalid_capture_policy_value_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    files["capture.yaml"]["defaults"]["message"]["capture_policy"] = "sell_it_all"
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_capture(tmp_path)


def test_audit_events_has_no_capture_kind(valid_config_dir: Path) -> None:
    """§7.3.1: a capture policy must never be able to suppress an audit
    row, so `audit_events` deliberately has no `CaptureKind` member."""
    assert "audit_events" not in {kind.value for kind in CaptureKind}
    assert {kind.value for kind in CaptureKind} == {
        "message",
        "plan",
        "llm_call",
        "tool_call",
        "memory",
    }
