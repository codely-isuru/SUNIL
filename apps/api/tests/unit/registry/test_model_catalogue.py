"""`sunil.core.registry.model_catalogue` — the model catalogue and
capability map (§4.4, §4.5)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from conftest import valid_config_files, write_config_dir
from sunil.core.registry.errors import (
    RegistrySchemaError,
    UnknownCapabilityError,
    UnknownModelError,
)
from sunil.core.registry.model_catalogue import load_models


def test_loads_the_pinned_price_table(valid_config_dir: Path) -> None:
    registry = load_models(valid_config_dir)

    sonnet = registry.get_model("claude-sonnet-5")

    assert sonnet.provider == "anthropic"
    assert sonnet.input_usd_per_mtok == Decimal("2")
    assert sonnet.output_usd_per_mtok == Decimal("10")
    assert sonnet.supports_structured_output is True
    assert registry.pricing_version == "2026-08-14"


def test_capability_lookup_resolves_to_a_model(valid_config_dir: Path) -> None:
    registry = load_models(valid_config_dir)

    general = registry.get_capability("general_reasoning")

    assert general.model == "claude-sonnet-5"
    assert general.timeout_s == 20


def test_unknown_model_raises_a_named_error_not_a_keyerror(valid_config_dir: Path) -> None:
    registry = load_models(valid_config_dir)

    with pytest.raises(UnknownModelError):
        registry.get_model("claude-does-not-exist")


def test_unknown_capability_raises_a_named_error_not_a_keyerror(valid_config_dir: Path) -> None:
    registry = load_models(valid_config_dir)

    with pytest.raises(UnknownCapabilityError):
        registry.get_capability("no_such_capability")


def test_capability_pointing_at_an_undefined_model_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    files["models.yaml"]["capabilities"]["general_reasoning"]["model"] = "claude-does-not-exist"
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_models(tmp_path)


def test_missing_pricing_version_fails_closed(tmp_path: Path) -> None:
    files = valid_config_files()
    del files["models.yaml"]["pricing_version"]
    write_config_dir(tmp_path, files)

    with pytest.raises(RegistrySchemaError):
        load_models(tmp_path)
