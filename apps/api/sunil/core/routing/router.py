"""The Model Router — SUNIL-owned capability × privacy policy (C2 §2).

``resolve()`` maps ``(capability, privacy_class) → (model alias, provider name)``
from ``config/models.yaml`` and enforces, **before any provider is selected**:

* ``LOCAL_ONLY`` resolves only to providers flagged ``local: true`` (none in
  Phase 0 — such a request is a routing error, never a silent downgrade,
  ROADMAP §26.10);
* a provider carrying ``max_privacy_class`` is ineligible above it — which is
  how the dev-lane provider (``omniroute``) stays ``PUBLIC``-only (ADR-030 §8).

Policy first, transport second, and **transport is invisible here**: this module
cannot see the ADR-033 lane flag (readable by provider registration alone — its
name deliberately does not appear in this package, see
``core/routing/__init__.py``) and takes its providers through the
``ProviderLookup`` protocol below, never by importing the module that wires
them. That is what makes the exclusion structural rather than a convention:
flipping the lane cannot widen which workloads reach a cloud provider, because
the decision that excludes them never reads the lane. The rule is enforced by
``tests/unit/routing/test_lane_flag_tripwire.py``.

``run()`` is the only way anything in SUNIL calls an LLM: it fixes
``CompletionRequest.model`` to the resolved alias (a caller's guess — or an
upstream id, which C2 §2 calls a config bug — never reaches the wire) and
dispatches through the one retry policy (C2 §4). Trace-stage emission is the
caller's job, exactly as in M1 (A-17): ``run()`` is invoked once per logical
request and a turn makes at least two, so emitting here would risk a duplicate
stage. What ``run()` does return is the per-attempt record and the A-2 usage
total the caller needs for its ``llm_calls`` rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from sunil.core.routing.catalogue import ModelCatalogue, privacy_rank
from sunil.core.routing.errors import (
    LocalOnlyUnavailableError,
    MaxTokensExceedsModelError,
    PrivacyClassNotPermittedError,
    StructuredOutputUnsupportedError,
)
from sunil.core.routing.retry import AttemptRecord, RetryPolicy
from sunil.providers.base import (
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    PrivacyClass,
    Usage,
)


@runtime_checkable
class ProviderLookup(Protocol):
    """What the router needs of a provider registry — nothing more.

    A protocol, not the concrete ``providers/registry.py`` class, precisely so
    this module never imports the only module allowed to read the ADR-033 lane
    flag (see the module docstring).
    """

    def get(self, name: str) -> LLMProvider: ...

    def provider_names(self) -> list[str]: ...


@dataclass(frozen=True)
class ResolvedRoute:
    capability: str
    model: str
    provider_name: str
    provider: LLMProvider
    max_tokens: int
    timeout_s: float


@dataclass(frozen=True)
class RoutedCompletion:
    result: CompletionResult
    route: ResolvedRoute
    attempts: tuple[AttemptRecord, ...]
    usage: Usage  # total across attempts, failures included (C2 §4 / M1 A-2)

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)


class ModelRouter:
    def __init__(
        self,
        *,
        catalogue: ModelCatalogue,
        providers: ProviderLookup,
        retry: RetryPolicy | None = None,
    ) -> None:
        self._catalogue = catalogue
        self._providers = providers
        self._retry = retry if retry is not None else RetryPolicy()

    @property
    def pricing_version(self) -> str:
        """Stamped onto the caller's ``llm_calls`` rows so a later price edit
        never rewrites the cost of a historical call (C2 §2)."""
        return self._catalogue.pricing_version

    def resolve(self, *, capability: str, privacy_class: PrivacyClass) -> ResolvedRoute:
        """Policy, then selection. Raises a named ``RoutingError`` subclass or a
        ``CatalogueError``; never returns a downgraded route."""
        capability_entry = self._catalogue.get_capability(capability)
        model = self._catalogue.get_model(capability_entry.model)
        provider_entry = self._catalogue.get_provider(model.provider)

        # ---- privacy policy: BEFORE the provider instance is looked up ----- #
        if privacy_class is PrivacyClass.LOCAL_ONLY and not provider_entry.local:
            raise LocalOnlyUnavailableError(capability=capability, provider=provider_entry.name)
        cap = provider_entry.max_privacy_class
        if cap is not None and privacy_rank(privacy_class) > privacy_rank(cap):
            raise PrivacyClassNotPermittedError(
                capability=capability,
                provider=provider_entry.name,
                requested=str(privacy_class),
                cap=str(cap),
            )

        # ---- transport selection: only now ------------------------------- #
        provider = self._providers.get(provider_entry.name)
        return ResolvedRoute(
            capability=capability,
            model=model.id,
            provider_name=provider_entry.name,
            provider=provider,
            max_tokens=capability_entry.max_tokens,
            timeout_s=capability_entry.timeout_s,
        )

    async def run(self, *, capability: str, request: CompletionRequest) -> RoutedCompletion:
        """One logical request, routed and retried.

        ``privacy_class`` is read from the request (C2 §2 puts it there), so
        there is no second privacy argument a caller could disagree with.
        """
        route = self.resolve(capability=capability, privacy_class=request.privacy_class)
        model = self._catalogue.get_model(route.model)
        if request.max_tokens > model.max_output:
            raise MaxTokensExceedsModelError(
                model=model.id, requested=request.max_tokens, max_output=model.max_output
            )
        if request.json_schema is not None and not model.supports_structured_output:
            raise StructuredOutputUnsupportedError(capability=capability, model=model.id)

        # C2 §2 — the model id on the wire is the ROUTER-resolved alias.
        routed_request = (
            request
            if request.model == route.model
            else request.model_copy(update={"model": route.model})
        )
        outcome = await self._retry.execute(
            provider=route.provider,
            request=routed_request,
            attempt_timeout_s=route.timeout_s,
        )
        return RoutedCompletion(
            result=outcome.result,
            route=route,
            attempts=outcome.attempts,
            usage=outcome.usage,
        )
