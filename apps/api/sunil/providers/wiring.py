"""`Settings` → Stream B's provider registry → one `LLMProvider` for the turn.

`providers/registry.py` says it plainly: its `LaneSettings.from_env` is "Stream
B's own minimal env reader … When the spine's `Settings` lands, it becomes the
single env seam and this loader should be replaced by an adapter over it — the
validators here are the behaviour that must survive that move." This module is
that adapter, and it keeps the validators: the ADR-033 named-host check runs
through `registry.validate_gateway_base_url`, the ADR-017 canonical-or-loopback
check through `registry.validate_direct_base_url`. One implementation of each
rule, called from both doors.

**Nothing here reads the environment.** `Settings` already did, once, with those
same rules applied at construction (C2 contract test 6 pins the gateway one);
this module re-runs them on the way out because the two files are separately
editable and "validated at both ends" is cheap insurance on an exfiltration
control.

**The router's namespace, not the vendor's.** `CatalogueRoutedProvider` resolves
`request.model` — always a `config/models.yaml` alias — to its provider through
the catalogue, then to the registered adapter. In the gateway lane every alias
resolves to the SAME `GatewayProvider` instance (one pool, one parity check); in
the direct lane each resolves to its vendor adapter. The orchestrator therefore
sees one `LLMProvider` and cannot tell the lanes apart, which is exactly ADR-033's
"flipping the kill switch changes no model id anywhere".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.providers.base import CompletionRequest, CompletionResult, StreamEvent
from sunil.providers.gateway import VirtualKeyring
from sunil.providers.registry import (
    LaneSettings,
    ProviderConfigurationError,
    ProviderRegistry,
    build_provider_registry,
    validate_direct_base_url,
    validate_gateway_base_url,
)
from sunil.providers.anthropic import CANONICAL_BASE_URL as ANTHROPIC_CANONICAL
from sunil.providers.openai import CANONICAL_BASE_URL as OPENAI_CANONICAL


def lane_settings_from(settings: Any) -> LaneSettings:
    """The `Settings` → `LaneSettings` adapter, validators included."""
    default_key = settings.litellm_virtual_key_default
    return LaneSettings(
        lane=settings.sunil_llm_provider_lane,
        gateway_base_url=validate_gateway_base_url(settings.sunil_llm_gateway_base_url),
        virtual_keys=(
            VirtualKeyring(default=default_key, per_agent={})
            if default_key is not None and default_key.get_secret_value()
            else None
        ),
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
        anthropic_base_url=validate_direct_base_url(
            settings.anthropic_base_url,
            canonical=ANTHROPIC_CANONICAL,
            field="ANTHROPIC_BASE_URL",
        ),
        openai_base_url=validate_direct_base_url(
            settings.openai_base_url, canonical=OPENAI_CANONICAL, field="OPENAI_BASE_URL"
        ),
    )


def load_catalogue(settings: Any) -> ModelCatalogue:
    """`config/models.yaml`, from the mounted config directory (ADR-016)."""
    return ModelCatalogue.load(Path(settings.sunil_config_dir) / "models.yaml")


def build_provider(settings: Any) -> CatalogueRoutedProvider:
    """The real C2 seam. Raises `ProviderConfigurationError` — a boot failure —
    rather than degrading a misconfigured lane into a working one that talks to a
    different host with a different credential."""
    catalogue = load_catalogue(settings)
    registry = build_provider_registry(
        settings=lane_settings_from(settings), catalogue=catalogue
    )
    return CatalogueRoutedProvider(registry=registry, catalogue=catalogue)


class CatalogueRoutedProvider:
    """C2 §2's `LLMProvider`, dispatching on the catalogue's model → provider map.

    Not a router: policy (capability × privacy) is `core/routing/router.py`'s and
    runs upstream, deciding WHICH model. This object only knows which adapter
    serves an already-chosen model id — transport, not policy — which is why it
    may see the lane and the router may not.
    """

    name = "catalogue"

    def __init__(self, *, registry: ProviderRegistry, catalogue: ModelCatalogue) -> None:
        self._registry = registry
        self._catalogue = catalogue

    def provider_for(self, model: str):
        entry = self._catalogue.get_model(model)
        return self._registry.get(entry.provider)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        return await self.provider_for(request.model).complete(request)

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        return self.provider_for(request.model).stream(request)

    async def start(self) -> None:
        """Every distinct adapter's startup check, exactly once — in the gateway
        lane that is C2 §3's model-parity check against the live gateway, which
        refuses to boot on a drifted alias namespace rather than serving a 400 on
        the first real turn."""
        from sunil.providers.registry import start_providers  # noqa: PLC0415

        await start_providers(self._registry)

    async def aclose(self) -> None:
        from sunil.providers.registry import close_providers  # noqa: PLC0415

        await close_providers(self._registry)


__all__ = [
    "CatalogueRoutedProvider",
    "ProviderConfigurationError",
    "build_provider",
    "lane_settings_from",
    "load_catalogue",
]
