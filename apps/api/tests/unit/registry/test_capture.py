"""`sunil.core.registry.capture` — training-data capture defaults (A-6,
ADR-014 + Amendment 1, §13.2, A-18).

`CaptureKind`/`CaptureRule` now live in the canonical `sunil.capture`
leaf module (ADR-014 Amendment 1) — this registry's job is the string ->
enum conversion, not defining the vocabulary."""

from __future__ import annotations

from pathlib import Path

import pytest
from sunil.capture import CaptureKind, CapturePolicy, CaptureRule, RetentionClass, Sensitivity
from sunil.core.registry.capture import load_capture
from sunil.core.registry.errors import RegistrySchemaError

from .registry_helpers import valid_config_files, write_config_dir


def test_loads_the_default_for_every_content_kind(valid_config_dir: Path) -> None:
    registry = load_capture(valid_config_dir)

    for kind in CaptureKind:
        rule = registry.defaults_for(kind)
        assert isinstance(rule, CaptureRule)
        assert rule.capture_policy is CapturePolicy.REDACTED_FULL
        assert rule.sensitivity is Sensitivity.INTERNAL

    # Memory is the one kind with shorter retention (§13.2 table).
    assert registry.defaults_for(CaptureKind.MEMORY).retention_class is RetentionClass.TRANSIENT
    assert registry.defaults_for(CaptureKind.MESSAGE).retention_class is RetentionClass.STANDARD


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
    assert overridden.capture_policy is CapturePolicy.METADATA_ONLY
    assert overridden.sensitivity is Sensitivity.CONFIDENTIAL

    # A kind the override does not mention still falls back to the default.
    unaffected = registry.defaults_for(CaptureKind.PLAN, project_key="easy_clean_workforce")
    assert unaffected.capture_policy is CapturePolicy.REDACTED_FULL


def test_unconfigured_project_key_never_raises_just_uses_the_default(
    valid_config_dir: Path,
) -> None:
    registry = load_capture(valid_config_dir)

    rule = registry.defaults_for(CaptureKind.MESSAGE, project_key="some_project_with_no_override")

    assert rule.capture_policy is CapturePolicy.REDACTED_FULL


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


def test_overrides_for_returns_the_exact_shape_resolve_capture_accepts(tmp_path: Path) -> None:
    """ADR-014 Amendment 1 point 3: `db/capture.py`'s `resolve_capture(
    overrides=...)` accepts `Mapping[CaptureKind, CaptureRule]` — this
    proves the registry hands back exactly that, with no translation
    needed at the call site."""
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

    overrides = registry.overrides_for("easy_clean_workforce")
    assert overrides == {
        CaptureKind.MESSAGE: CaptureRule(
            capture_policy=CapturePolicy.METADATA_ONLY,
            sensitivity=Sensitivity.CONFIDENTIAL,
            retention_class=RetentionClass.STANDARD,
        )
    }
    # An unconfigured project has an empty override mapping, never raises.
    assert registry.overrides_for("no_such_project") == {}


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


def test_unknown_content_kind_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    files["capture.yaml"]["defaults"]["some_made_up_kind"] = {
        "capture_policy": "redacted_full",
        "sensitivity": "internal",
        "retention_class": "standard",
    }
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
