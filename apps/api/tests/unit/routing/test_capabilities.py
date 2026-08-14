"""`sunil.core.routing.capabilities` — capability -> provider/model
resolution (§4.5)."""

from __future__ import annotations

import pytest
from sunil.core.registry.errors import UnknownCapabilityError
from sunil.core.routing.capabilities import resolve_capability
from sunil.providers.base import UnknownProviderError

from .conftest import FakeProvider, make_model_registry, make_provider_registry


def test_resolves_a_configured_capability_to_its_provider_and_model() -> None:
    fake = FakeProvider("fake", capabilities_by_model={}, responses=[])
    model_registry = make_model_registry(
        capability="general_reasoning", provider="fake", model="fake-model-1", timeout_s=20.0
    )
    provider_registry = make_provider_registry(fake)

    resolved = resolve_capability(
        "general_reasoning", model_registry=model_registry, provider_registry=provider_registry
    )

    assert resolved.provider is fake
    assert resolved.model == "fake-model-1"
    assert resolved.timeout_s == 20.0


def test_unknown_capability_raises_a_named_error_not_a_keyerror() -> None:
    model_registry = make_model_registry()
    provider_registry = make_provider_registry()

    with pytest.raises(UnknownCapabilityError):
        resolve_capability(
            "no_such_capability", model_registry=model_registry, provider_registry=provider_registry
        )


def test_capability_naming_an_unregistered_provider_raises_a_named_error() -> None:
    """The capability is well-formed in `config/models.yaml`, but nobody
    registered a provider under that name — still fails closed, not with
    a `KeyError`."""
    model_registry = make_model_registry(provider="never_registered")
    provider_registry = make_provider_registry()  # empty

    with pytest.raises(UnknownProviderError):
        resolve_capability(
            "general_reasoning", model_registry=model_registry, provider_registry=provider_registry
        )
