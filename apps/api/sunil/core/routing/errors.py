"""Named, fail-closed errors for the routing layer.

Every lookup miss and every policy refusal has a name here. Ported M1 rule: a
router never raises a bare ``KeyError`` — the message must say what was asked
for, where the answer was supposed to come from, and (for a policy refusal) which
rule refused, because the caller turning this into a C5 ``failure`` has no other
source of that detail.
"""

from __future__ import annotations

from collections.abc import Iterable


class CatalogueError(Exception):
    """``config/models.yaml`` is wrong or incomplete — a boot/config fault."""


class UnknownCapabilityError(CatalogueError):
    def __init__(self, capability: str) -> None:
        super().__init__(
            f"capability {capability!r} is not declared in config/models.yaml "
            "(`capabilities:`)"
        )
        self.capability = capability


class UnknownModelError(CatalogueError):
    def __init__(self, model: str) -> None:
        super().__init__(f"model {model!r} is not declared in config/models.yaml (`models:`)")
        self.model = model


class UnknownProviderError(CatalogueError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            f"provider {provider!r} is not declared in config/models.yaml (`providers:`)"
        )
        self.provider = provider


class ModelNamespaceError(CatalogueError):
    """C2 §2 — ``config/models.yaml`` ids MUST equal the gateway alias set
    verbatim. A drifted namespace is a config bug, caught at boot."""

    def __init__(self, *, unexpected: Iterable[str], missing: Iterable[str]) -> None:
        unexpected = sorted(unexpected)
        missing = sorted(missing)
        super().__init__(
            "config/models.yaml model ids must equal the LiteLLM gateway alias set "
            f"verbatim (C2 §2). Not in the alias set: {unexpected or 'none'}; "
            f"declared by the gateway but missing here: {missing or 'none'}."
        )
        self.unexpected = tuple(unexpected)
        self.missing = tuple(missing)


class RoutingError(Exception):
    """A request cannot be routed. Never a downgrade, never a default."""


class LocalOnlyUnavailableError(RoutingError):
    """C2 §2 / §26.10 — ``LOCAL_ONLY`` resolves only to providers flagged
    ``local: true``; none exist in Phase 0, so this fails closed."""

    def __init__(self, *, capability: str, provider: str) -> None:
        super().__init__(
            f"privacy_class=local_only cannot be served: capability {capability!r} "
            f"resolves to provider {provider!r}, which is not flagged `local: true` "
            "in config/models.yaml. A LOCAL_ONLY request is a routing error, never "
            "a silent downgrade to a remote model (C2 §2, ROADMAP §26.10)."
        )
        self.capability = capability
        self.provider = provider


class PrivacyClassNotPermittedError(RoutingError):
    """The resolved provider is capped below the request's privacy class — the
    dev-lane provider (``omniroute``) is eligible for ``PUBLIC`` only
    (ADR-030 §8)."""

    def __init__(
        self, *, capability: str, provider: str, requested: str, cap: str
    ) -> None:
        super().__init__(
            f"capability {capability!r} resolves to provider {provider!r}, which is "
            f"capped at privacy_class={cap} — this request is {requested} "
            "(config/models.yaml `max_privacy_class:`; ADR-030 §8 admits the dev "
            "lane for PUBLIC workloads only)"
        )
        self.capability = capability
        self.provider = provider


class MaxTokensExceedsModelError(RoutingError):
    """The request asks for more output than the resolved model can produce.

    Fail loudly rather than clamp: a silently shortened answer is a correctness
    bug the caller cannot see, and on the plan stage it is an ``invalid_output``
    with a misleading cause.
    """

    def __init__(self, *, model: str, requested: int, max_output: int) -> None:
        super().__init__(
            f"max_tokens={requested} exceeds max_output={max_output} for model "
            f"{model!r} (config/models.yaml). Lower max_tokens or route to a model "
            "with a larger ceiling — the router does not clamp silently."
        )
        self.model = model
        self.requested = requested
        self.max_output = max_output


class StructuredOutputUnsupportedError(RoutingError):
    """A ``json_schema`` request resolved to a model the catalogue marks
    ``supports_structured_output: false``.

    Refused here rather than sent: the plan stage is structured output or it is
    rejected (ROADMAP §25), so sending it as free text would surface as an
    ``invalid_output`` whose real cause (a config mismatch) is invisible.
    """

    def __init__(self, *, capability: str, model: str) -> None:
        super().__init__(
            f"capability {capability!r} resolves to model {model!r}, which "
            "config/models.yaml marks `supports_structured_output: false` — a "
            "schema-bearing request must not be sent as free text (C2 §2, §25)"
        )
        self.capability = capability
        self.model = model


class ProviderNotRegisteredError(RoutingError):
    """The catalogue names a provider that nothing registered — a startup wiring
    fault (in the gateway lane, the gateway is registered under every non-local
    provider name; in the direct lane, one adapter per key present)."""

    def __init__(self, provider: str) -> None:
        super().__init__(
            f"no provider registered under the name {provider!r} — check provider "
            "registration (sunil/providers/registry.py) against "
            "config/models.yaml `providers:`"
        )
        self.provider = provider
