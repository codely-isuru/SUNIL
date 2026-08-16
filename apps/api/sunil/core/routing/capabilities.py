"""Capability -> `{provider, model, max_tokens, timeout_s}` resolution
(§4.5) — the one place an agent's declared capability name (or the
orchestrator's own plan-generation call) turns into a concrete provider
and model. Nothing above this layer ever names a vendor or a model ID
(§33 rule 1, ADR-003).
"""

from __future__ import annotations

from dataclasses import dataclass

from sunil.core.registry.model_catalogue import ModelRegistry
from sunil.providers.base import LLMProvider
from sunil.providers.registry import ProviderRegistry


@dataclass(frozen=True)
class ResolvedCapability:
    capability: str
    provider: LLMProvider
    model: str
    max_tokens: int
    timeout_s: float


def resolve_capability(
    capability: str,
    *,
    model_registry: ModelRegistry,
    provider_registry: ProviderRegistry,
) -> ResolvedCapability:
    """Raises `UnknownCapabilityError` (the capability is not in
    `config/models.yaml`) or `UnknownProviderError` (the capability names a
    provider nobody registered) — both named, fail-closed errors, never a
    bare `KeyError`.
    """
    definition = model_registry.get_capability(capability)
    provider = provider_registry.get(definition.provider)
    return ResolvedCapability(
        capability=capability,
        provider=provider,
        model=definition.model,
        max_tokens=definition.max_tokens,
        timeout_s=definition.timeout_s,
    )
