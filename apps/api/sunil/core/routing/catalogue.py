"""``config/models.yaml`` — the model catalogue the SUNIL router reads (C2 §2).

Three tables, cross-validated at load so a config fault is a boot failure and
never a runtime 400:

``providers:``    name → ``{local, lane, max_privacy_class}``. Privacy
                  eligibility lives here, NOT in the transport: ``local: true``
                  is what makes a provider admissible for ``LOCAL_ONLY``, and
                  ``max_privacy_class`` is what caps the dev lane at ``PUBLIC``
                  (ADR-030 §8).
``models:``       gateway ALIAS → pricing/limits + ``provider_model_id``. The
                  alias namespace is the LiteLLM ``model_name`` set verbatim
                  (C2 §2) and is **lane-invariant**: ``provider_model_id`` (the
                  provider-native id) is read ONLY by the direct-lane adapters,
                  so flipping the ADR-033 kill switch changes no model id
                  anywhere.
``capabilities:`` capability → ``{model, max_tokens, timeout_s}``. Callers name
                  a capability, never a vendor or a model.

Every key is declared: an undeclared key in the YAML is a load error, the same
closed-model discipline C2 §2 applies to the wire models (a typo'd
``inputs_usd_per_mtok`` must not silently price a model at zero).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

from sunil.core.routing.errors import (
    CatalogueError,
    ModelNamespaceError,
    UnknownCapabilityError,
    UnknownModelError,
    UnknownProviderError,
)
from sunil.providers.base import GATEWAY_MODEL_ALIASES, PrivacyClass

#: Privacy classes ordered by sensitivity — used only to compare a request's
#: class against a provider's declared ceiling.
_PRIVACY_ORDER: tuple[PrivacyClass, ...] = (
    PrivacyClass.PUBLIC,
    PrivacyClass.INTERNAL,
    PrivacyClass.CONFIDENTIAL,
    PrivacyClass.LOCAL_ONLY,
)


def privacy_rank(privacy_class: PrivacyClass) -> int:
    return _PRIVACY_ORDER.index(privacy_class)


@dataclass(frozen=True)
class ProviderEntry:
    name: str
    local: bool
    lane: Literal["prod", "dev"]
    max_privacy_class: PrivacyClass | None


@dataclass(frozen=True)
class ModelEntry:
    id: str
    provider: str
    provider_model_id: str
    context_window: int
    max_output: int
    input_usd_per_mtok: Decimal
    output_usd_per_mtok: Decimal
    supports_structured_output: bool


@dataclass(frozen=True)
class CapabilityEntry:
    name: str
    model: str
    max_tokens: int
    timeout_s: float


_PROVIDER_KEYS = {"local", "lane", "max_privacy_class"}
_MODEL_KEYS = {
    "provider",
    "provider_model_id",
    "context_window",
    "max_output",
    "input_usd_per_mtok",
    "output_usd_per_mtok",
    "supports_structured_output",
    "pricing_verified",
    "notes",
}
_CAPABILITY_KEYS = {"model", "max_tokens", "timeout_s", "notes"}
_TOP_LEVEL_KEYS = {"version", "pricing_version", "providers", "models", "capabilities"}


def _require(mapping: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise CatalogueError(f"{where}: required key {key!r} is missing")
    return mapping[key]


def _reject_unknown_keys(mapping: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise CatalogueError(
            f"{where}: undeclared key(s) {unknown} — a typo must not be silently "
            f"ignored. Allowed: {sorted(allowed)}"
        )


def _decimal(value: Any, where: str, key: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CatalogueError(f"{where}: {key}={value!r} is not a decimal number") from exc


class ModelCatalogue:
    """Parsed, cross-validated ``config/models.yaml``."""

    def __init__(
        self,
        *,
        version: int,
        pricing_version: str,
        providers: Mapping[str, ProviderEntry],
        models: Mapping[str, ModelEntry],
        capabilities: Mapping[str, CapabilityEntry],
    ) -> None:
        self.version = version
        self.pricing_version = pricing_version
        self._providers = dict(providers)
        self._models = dict(models)
        self._capabilities = dict(capabilities)

    # -- construction ------------------------------------------------------- #
    @classmethod
    def load(cls, path: str | Path) -> ModelCatalogue:
        """Parse the YAML at ``path``. ``yaml`` is imported lazily so importing
        this module (which the router does) never requires the parser."""
        import yaml  # noqa: PLC0415 — lazy on purpose, see docstring

        source = Path(path)
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CatalogueError(f"model catalogue not found: {source}") from exc
        except yaml.YAMLError as exc:
            raise CatalogueError(f"{source}: not valid YAML: {exc}") from exc
        if not isinstance(raw, Mapping):
            raise CatalogueError(f"{source}: top level must be a mapping")
        return cls.from_mapping(raw, where=str(source))

    @classmethod
    def from_mapping(
        cls, data: Mapping[str, Any], *, where: str = "config/models.yaml"
    ) -> ModelCatalogue:
        _reject_unknown_keys(data, _TOP_LEVEL_KEYS, where)
        version = int(_require(data, "version", where))
        pricing_version = str(_require(data, "pricing_version", where))

        providers: dict[str, ProviderEntry] = {}
        for name, body in dict(_require(data, "providers", where)).items():
            location = f"{where}: providers.{name}"
            _reject_unknown_keys(body, _PROVIDER_KEYS, location)
            cap = body.get("max_privacy_class")
            lane = str(body.get("lane", "prod"))
            if lane not in ("prod", "dev"):
                raise CatalogueError(f"{location}: lane must be 'prod' or 'dev', not {lane!r}")
            providers[name] = ProviderEntry(
                name=name,
                local=bool(_require(body, "local", location)),
                lane=lane,  # type: ignore[arg-type]
                max_privacy_class=None if cap is None else PrivacyClass(str(cap)),
            )

        models: dict[str, ModelEntry] = {}
        for model_id, body in dict(_require(data, "models", where)).items():
            location = f"{where}: models.{model_id}"
            _reject_unknown_keys(body, _MODEL_KEYS, location)
            provider = str(_require(body, "provider", location))
            if provider not in providers:
                raise CatalogueError(
                    f"{location}: provider {provider!r} is not declared under "
                    "`providers:` — a model nobody can serve is a config bug"
                )
            models[model_id] = ModelEntry(
                id=model_id,
                provider=provider,
                provider_model_id=str(_require(body, "provider_model_id", location)),
                context_window=int(_require(body, "context_window", location)),
                max_output=int(_require(body, "max_output", location)),
                input_usd_per_mtok=_decimal(
                    _require(body, "input_usd_per_mtok", location),
                    location,
                    "input_usd_per_mtok",
                ),
                output_usd_per_mtok=_decimal(
                    _require(body, "output_usd_per_mtok", location),
                    location,
                    "output_usd_per_mtok",
                ),
                supports_structured_output=bool(
                    _require(body, "supports_structured_output", location)
                ),
            )

        capabilities: dict[str, CapabilityEntry] = {}
        for name, body in dict(_require(data, "capabilities", where)).items():
            location = f"{where}: capabilities.{name}"
            _reject_unknown_keys(body, _CAPABILITY_KEYS, location)
            model = str(_require(body, "model", location))
            if model not in models:
                raise CatalogueError(
                    f"{location}: model {model!r} is not declared under `models:` — "
                    "a capability that cannot resolve is a boot failure, not a "
                    "runtime 400"
                )
            max_tokens = int(_require(body, "max_tokens", location))
            if max_tokens > models[model].max_output:
                raise CatalogueError(
                    f"{location}: max_tokens={max_tokens} exceeds max_output="
                    f"{models[model].max_output} of model {model!r}"
                )
            capabilities[name] = CapabilityEntry(
                name=name,
                model=model,
                max_tokens=max_tokens,
                timeout_s=float(_require(body, "timeout_s", location)),
            )

        return cls(
            version=version,
            pricing_version=pricing_version,
            providers=providers,
            models=models,
            capabilities=capabilities,
        )

    # -- lookups ------------------------------------------------------------ #
    def get_provider(self, name: str) -> ProviderEntry:
        try:
            return self._providers[name]
        except KeyError:
            raise UnknownProviderError(name) from None

    def get_model(self, model_id: str) -> ModelEntry:
        try:
            return self._models[model_id]
        except KeyError:
            raise UnknownModelError(model_id) from None

    def get_capability(self, name: str) -> CapabilityEntry:
        try:
            return self._capabilities[name]
        except KeyError:
            raise UnknownCapabilityError(name) from None

    def model_ids(self) -> tuple[str, ...]:
        return tuple(self._models)

    def provider_names(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def capability_names(self) -> tuple[str, ...]:
        return tuple(self._capabilities)

    def remote_provider_names(self) -> tuple[str, ...]:
        """Providers reached over the network — i.e. everything the gateway lane
        can serve. A ``local: true`` provider is deliberately excluded: it is not
        a LiteLLM deployment and must never be silently satisfied by one."""
        return tuple(name for name, entry in self._providers.items() if not entry.local)

    # -- validation --------------------------------------------------------- #
    def validate_gateway_alias_namespace(
        self, aliases: tuple[str, ...] = GATEWAY_MODEL_ALIASES
    ) -> None:
        """C2 §2 — the ids here MUST equal the gateway alias set verbatim.

        Checked in both directions: an extra id would be a request the gateway
        400s, and a missing one silently removes a model from the router's
        reach.
        """
        declared = set(self.model_ids())
        expected = set(aliases)
        if declared != expected:
            raise ModelNamespaceError(
                unexpected=declared - expected, missing=expected - declared
            )
