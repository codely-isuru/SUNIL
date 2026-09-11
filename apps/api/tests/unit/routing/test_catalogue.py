"""``config/models.yaml`` loader — the catalogue the SUNIL router reads.

C2 §2's normative rules under test here:

* model ids MUST equal the LiteLLM gateway alias set VERBATIM
  (``claude-sonnet``, ``claude-opus``, ``claude-haiku``, ``gpt-flagship``,
  ``gpt-mini``) — an upstream id in this namespace is a config bug;
* every entry additionally carries ``provider_model_id:``, which ONLY the
  direct-lane adapters read, so the router namespace is lane-invariant;
* unknown capability/model/provider lookups raise NAMED errors, never a bare
  ``KeyError`` (M1 rule ported).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.core.routing.errors import (
    CatalogueError,
    ModelNamespaceError,
    UnknownCapabilityError,
    UnknownModelError,
    UnknownProviderError,
)
from sunil.providers.base import GATEWAY_MODEL_ALIASES, PrivacyClass
from tests.unit.routing.catalogues import fake_only, fake_only_mapping


def repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "config").is_dir() and (parent / "docs" / "contracts").is_dir():
            return parent
    raise AssertionError("repo root (the directory holding config/ and docs/) not found")


def real_catalogue() -> ModelCatalogue:
    return ModelCatalogue.load(repo_root() / "config" / "models.yaml")


# --------------------------------------------------------------------------- #
# the real file
# --------------------------------------------------------------------------- #
def test_real_models_yaml_ids_equal_the_gateway_alias_namespace() -> None:
    """C2 §2 — ``config/models.yaml`` ids MUST equal LiteLLM's ``model_name``
    alias set verbatim. Not a superset, not a subset: equal."""
    catalogue = real_catalogue()

    assert set(catalogue.model_ids()) == set(GATEWAY_MODEL_ALIASES)
    catalogue.validate_gateway_alias_namespace()  # must not raise


def test_real_models_yaml_carries_a_direct_lane_provider_model_id_per_entry() -> None:
    """C2 §2 — ``provider_model_id:`` (the provider-native id) is what the
    DIRECT-lane adapters resolve; it must never leak into the router namespace."""
    catalogue = real_catalogue()

    for model_id in catalogue.model_ids():
        entry = catalogue.get_model(model_id)
        assert entry.provider_model_id, f"{model_id} has no provider_model_id"
        assert entry.provider_model_id != model_id, (
            f"{model_id}: provider_model_id repeats the gateway alias — the direct "
            "lane would then ask the vendor for an alias only the gateway knows"
        )
        assert entry.provider in {"anthropic", "openai"}


def test_real_models_yaml_capabilities_all_resolve() -> None:
    """A capability pointing at a model that does not exist is a boot-time
    config bug, not a runtime 400."""
    catalogue = real_catalogue()

    assert catalogue.capability_names(), "the catalogue declares no capabilities"
    for name in catalogue.capability_names():
        capability = catalogue.get_capability(name)
        model = catalogue.get_model(capability.model)
        assert capability.max_tokens <= model.max_output
        assert capability.timeout_s > 0
        catalogue.get_provider(model.provider)


def test_real_models_yaml_declares_no_local_provider_in_phase_0() -> None:
    """C2 §2 — "none in Phase 0": a ``LOCAL_ONLY`` request must fail closed, so
    this asserts the *absence* the router's fail-closed path depends on. When a
    local provider is added, this test is the reminder to prove the positive
    path too."""
    catalogue = real_catalogue()

    assert [p for p in catalogue.provider_names() if catalogue.get_provider(p).local] == []


# --------------------------------------------------------------------------- #
# namespace validation
# --------------------------------------------------------------------------- #
def test_upstream_style_model_id_is_rejected_by_namespace_validation() -> None:
    """C2 §2 — ``anthropic/claude-sonnet-4-5`` as a *catalogue id* is a config
    bug: upstream ids live only inside the gateway's own config."""
    mapping = fake_only_mapping()
    mapping["models"]["anthropic/claude-sonnet-4-5"] = mapping["models"]["claude-sonnet"]
    catalogue = ModelCatalogue.from_mapping(mapping)

    with pytest.raises(ModelNamespaceError) as err:
        catalogue.validate_gateway_alias_namespace()

    assert "anthropic/claude-sonnet-4-5" in str(err.value)


def test_namespace_validation_names_every_offender_not_just_the_first() -> None:
    mapping = fake_only_mapping()
    mapping["models"].pop("claude-sonnet")
    mapping["models"]["mystery-model"] = {
        "provider": "fake",
        "provider_model_id": "x-1",
        "context_window": 8192,
        "max_output": 8192,
        "input_usd_per_mtok": "0",
        "output_usd_per_mtok": "0",
        "supports_structured_output": False,
    }
    mapping["capabilities"]["general_reasoning"]["model"] = "mystery-model"
    catalogue = ModelCatalogue.from_mapping(mapping)

    with pytest.raises(ModelNamespaceError) as err:
        catalogue.validate_gateway_alias_namespace()

    message = str(err.value)
    assert "mystery-model" in message
    # ...and the four aliases the catalogue is MISSING are named too, because a
    # subset drifts just as loudly as a superset.
    for missing_alias in ("claude-opus", "claude-haiku", "gpt-flagship", "gpt-mini"):
        assert missing_alias in message


# --------------------------------------------------------------------------- #
# named errors, never KeyError
# --------------------------------------------------------------------------- #
def test_unknown_lookups_raise_named_errors() -> None:
    catalogue = fake_only()

    with pytest.raises(UnknownCapabilityError):
        catalogue.get_capability("nope")
    with pytest.raises(UnknownModelError):
        catalogue.get_model("nope")
    with pytest.raises(UnknownProviderError):
        catalogue.get_provider("nope")
    # All three are CatalogueErrors, so a caller can fail closed on one except.
    assert issubclass(UnknownCapabilityError, CatalogueError)
    assert issubclass(UnknownModelError, CatalogueError)
    assert issubclass(UnknownProviderError, CatalogueError)


def test_a_model_naming_an_undeclared_provider_fails_at_load() -> None:
    """Cross-validation at load, not at the first request that routes there."""
    mapping = fake_only_mapping()
    mapping["models"]["claude-sonnet"]["provider"] = "ghost"

    with pytest.raises(CatalogueError, match="ghost"):
        ModelCatalogue.from_mapping(mapping)


def test_a_capability_naming_an_undeclared_model_fails_at_load() -> None:
    mapping = fake_only_mapping()
    mapping["capabilities"]["general_reasoning"]["model"] = "ghost-model"

    with pytest.raises(CatalogueError, match="ghost-model"):
        ModelCatalogue.from_mapping(mapping)


def test_missing_provider_model_id_fails_at_load() -> None:
    """The direct lane cannot be silently unroutable: the fallback lane's ids
    are validated in BOTH lanes, at load, so flipping the ADR-033 kill switch
    can never discover a missing id at 3am."""
    mapping = fake_only_mapping()
    del mapping["models"]["claude-sonnet"]["provider_model_id"]

    with pytest.raises(CatalogueError, match="provider_model_id"):
        ModelCatalogue.from_mapping(mapping)


def test_an_undeclared_key_in_the_yaml_is_a_load_error() -> None:
    """A typo'd key (``inputs_usd_per_mtok``) must not be silently ignored — the
    same closed-model discipline C2 §2 applies to the wire models."""
    mapping = fake_only_mapping()
    mapping["models"]["claude-sonnet"]["inputs_usd_per_mtok"] = "9"

    with pytest.raises(CatalogueError, match="inputs_usd_per_mtok"):
        ModelCatalogue.from_mapping(mapping)


# --------------------------------------------------------------------------- #
# typed values
# --------------------------------------------------------------------------- #
def test_prices_are_decimals_not_floats() -> None:
    """Prices are read as ``Decimal`` from quoted strings (M1 rule): binary
    floats cannot represent a price table exactly, and cost is money."""
    entry = real_catalogue().get_model("claude-sonnet")

    assert isinstance(entry.input_usd_per_mtok, Decimal)
    assert isinstance(entry.output_usd_per_mtok, Decimal)
    assert entry.input_usd_per_mtok > 0


def test_provider_privacy_cap_is_parsed_into_the_enum() -> None:
    from tests.unit.routing.catalogues import with_local_and_dev_providers

    catalogue = with_local_and_dev_providers()

    assert catalogue.get_provider("omniroute").max_privacy_class is PrivacyClass.PUBLIC
    assert catalogue.get_provider("omniroute").lane == "dev"
    assert catalogue.get_provider("fake").max_privacy_class is None
    assert catalogue.get_provider("fake_local").local is True


def test_pricing_version_is_carried_so_a_price_edit_never_rewrites_history() -> None:
    assert real_catalogue().pricing_version
