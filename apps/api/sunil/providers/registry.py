"""Provider registration — and the ONLY module in SUNIL that reads the ADR-033
transport lane flag.

ADR-033's kill switch is **population-scoped**: ``SUNIL_LLM_PROVIDER_LANE``
(``gateway`` | ``direct``, default ``gateway``) selects transport wiring at
startup and is readable here and nowhere else. ``core/routing`` — where
capability and privacy policy live — must not be able to see it, directly or
through an import, so that flipping the lane can never widen which workloads
reach a cloud provider (central-memory lesson 2026-08-17: the excluded
population's decision must not take the mode as input). That property is
enforced mechanically by ``tests/unit/routing/test_lane_flag_tripwire.py``.

**Lane-invariance is mechanical here too.** The registry keys are the
``config/models.yaml`` provider names in BOTH lanes:

* gateway lane → the single ``GatewayProvider`` is registered under EVERY
  non-local provider name in the catalogue, because on that lane LiteLLM serves
  all of them;
* direct lane → one vendor adapter per provider name whose API key is present.

So the router resolves ``anthropic``/``openai`` identically either way and needs
no change when the switch is flipped.

**Thin settings loader.** ``LaneSettings.from_env`` is Stream B's own minimal
env reader, existing because the rebuilt ``sunil/settings.py`` (Stream A) is not
in this worktree. It is deliberately not laxer than the real thing: the ADR-033
gateway validator and the ADR-017 canonical-or-loopback validator for the direct
lane are both implemented and tested below. When the spine's ``Settings`` lands,
it becomes the single env seam and this loader should be replaced by an adapter
over it — the validators here are the behaviour that must survive that move.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import SecretStr

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.core.routing.errors import ProviderNotRegisteredError
from sunil.providers.anthropic import AnthropicProvider
from sunil.providers.anthropic import CANONICAL_BASE_URL as ANTHROPIC_CANONICAL
from sunil.providers.base import LLMProvider
from sunil.providers.gateway import GatewayProvider, VirtualKeyring
from sunil.providers.openai import CANONICAL_BASE_URL as OPENAI_CANONICAL
from sunil.providers.openai import OpenAIProvider

#: ADR-033's kill switch. This is the one module allowed to name it.
LANE_ENV_VAR = "SUNIL_LLM_PROVIDER_LANE"

GATEWAY_BASE_URL_ENV = "SUNIL_LLM_GATEWAY_BASE_URL"
DEFAULT_GATEWAY_BASE_URL = "http://localhost:4000"
VIRTUAL_KEY_DEFAULT_ENV = "LITELLM_VIRTUAL_KEY_DEFAULT"
VIRTUAL_KEY_PREFIX = "LITELLM_VIRTUAL_KEY_"

#: ADR-033 — the named-host set is a FROZEN CONSTANT IN CODE, not configuration:
#: adding a host is a code change with review, never an env edit. It holds
#: exactly the ADR-032 Compose service names SUNIL legitimately calls; only
#: ``litellm`` is admissible for the gateway field.
NAMED_GATEWAY_HOSTS = frozenset({"litellm"})

Lane = Literal["gateway", "direct"]


class ProviderConfigurationError(Exception):
    """The process is misconfigured for the selected lane — a boot failure.

    Never degraded into "start anyway with less": a gateway lane with no virtual
    key that silently fell back to direct calls would send prompts to a
    different host with a different credential than the operator configured.
    """


@runtime_checkable
class _Startable(Protocol):
    async def start(self) -> None: ...


# --------------------------------------------------------------------------- #
# base-URL validation
# --------------------------------------------------------------------------- #
def _host_is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def validate_gateway_base_url(url: str, *, field: str = GATEWAY_BASE_URL_ENV) -> str:
    """ADR-033: ``host(url)`` is loopback, or the literal Compose service host
    ``litellm``, or the app refuses to boot.

    Rejected by design: any RFC-1918/private host (that is the whole LAN, and a
    redirected gateway URL carries every prompt and virtual key with it), and
    any suffix match (``litellm.evil.example`` is not ``litellm``).
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ProviderConfigurationError(
            f"{field}={url!r} is not an absolute http(s) URL (ADR-033)"
        )
    host = (parts.hostname or "").lower()
    if _host_is_loopback(host) or host in NAMED_GATEWAY_HOSTS:
        return url
    raise ProviderConfigurationError(
        f"{field}={url!r} names host {host!r}. ADR-033 admits ONLY loopback or the "
        f"literal Compose host(s) {sorted(NAMED_GATEWAY_HOSTS)} — the named-host set "
        "is a code-level constant precisely so it is unreachable from the "
        "environment. Refusing to boot."
    )


def validate_direct_base_url(url: str, *, canonical: str, field: str) -> str:
    """ADR-017, unchanged for the direct lane: the canonical public value, or
    loopback (QA's test doubles), or refuse. ``litellm`` is NOT admissible here —
    ADR-033's named-host extension is scoped to the gateway field."""
    if url.rstrip("/") == canonical.rstrip("/"):
        return url
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and _host_is_loopback((parts.hostname or "").lower()):
        return url
    raise ProviderConfigurationError(
        f"{field}={url!r} is neither the canonical {canonical!r} nor loopback "
        "(ADR-017). An env-settable, unguarded base URL is an exfiltration channel: "
        "it carries the Authorization header to whatever host is named."
    )


# --------------------------------------------------------------------------- #
# the thin settings loader
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class LaneSettings:
    lane: Lane
    gateway_base_url: str
    virtual_keys: VirtualKeyring | None
    anthropic_api_key: SecretStr | None
    openai_api_key: SecretStr | None
    anthropic_base_url: str
    openai_base_url: str

    def __repr__(self) -> str:  # pragma: no cover - trivial, but load-bearing
        """Secrets are ``SecretStr`` and this class holds a keyring; the repr
        names only which keys EXIST, never their values (ADR-006)."""
        agents = sorted(self.virtual_keys.per_agent) if self.virtual_keys else []
        return (
            f"LaneSettings(lane={self.lane!r}, gateway_base_url={self.gateway_base_url!r}, "
            f"virtual_key_default={'set' if self.virtual_keys else 'unset'}, "
            f"per_agent_keys={agents}, "
            f"anthropic_api_key={'set' if self.anthropic_api_key else 'unset'}, "
            f"openai_api_key={'set' if self.openai_api_key else 'unset'}, "
            f"anthropic_base_url={self.anthropic_base_url!r}, "
            f"openai_base_url={self.openai_base_url!r})"
        )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> LaneSettings:
        """Read the lane configuration. ``env`` is injectable so every test runs
        without touching the real process environment."""
        source = os.environ if env is None else env

        lane = (source.get(LANE_ENV_VAR) or "gateway").strip().lower()
        if lane not in ("gateway", "direct"):
            raise ProviderConfigurationError(
                f"{LANE_ENV_VAR}={lane!r} is not a lane: expected 'gateway' or 'direct' "
                "(ADR-033)"
            )

        gateway_base_url = validate_gateway_base_url(
            source.get(GATEWAY_BASE_URL_ENV) or DEFAULT_GATEWAY_BASE_URL
        )

        default_key = source.get(VIRTUAL_KEY_DEFAULT_ENV)
        per_agent = {
            name[len(VIRTUAL_KEY_PREFIX) :].lower(): SecretStr(value)
            for name, value in source.items()
            if name.startswith(VIRTUAL_KEY_PREFIX)
            and name != VIRTUAL_KEY_DEFAULT_ENV
            and value
        }
        keyring = (
            VirtualKeyring(default=SecretStr(default_key), per_agent=per_agent)
            if default_key
            else None
        )

        anthropic_key = source.get("ANTHROPIC_API_KEY") or None
        openai_key = source.get("OPENAI_API_KEY") or None

        return cls(
            lane=lane,  # type: ignore[arg-type]
            gateway_base_url=gateway_base_url,
            virtual_keys=keyring,
            anthropic_api_key=SecretStr(anthropic_key) if anthropic_key else None,
            openai_api_key=SecretStr(openai_key) if openai_key else None,
            anthropic_base_url=validate_direct_base_url(
                source.get("ANTHROPIC_BASE_URL") or ANTHROPIC_CANONICAL,
                canonical=ANTHROPIC_CANONICAL,
                field="ANTHROPIC_BASE_URL",
            ),
            openai_base_url=validate_direct_base_url(
                source.get("OPENAI_BASE_URL") or OPENAI_CANONICAL,
                canonical=OPENAI_CANONICAL,
                field="OPENAI_BASE_URL",
            ),
        )


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
class ProviderRegistry:
    """Name → provider, where the name is a ``config/models.yaml`` provider (not
    the adapter's own ``name``, which describes the transport: in the gateway
    lane every entry is the one adapter whose ``name`` is ``gateway``).

    Satisfies ``core.routing.router.ProviderLookup`` structurally — the router
    depends on that protocol and never imports this module (ADR-033).
    """

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}

    def register(self, name: str, provider: LLMProvider) -> None:
        self._providers[name] = provider

    def get(self, name: str) -> LLMProvider:
        try:
            return self._providers[name]
        except KeyError:
            raise ProviderNotRegisteredError(name) from None

    def provider_names(self) -> list[str]:
        return list(self._providers)

    def unique_providers(self) -> list[LLMProvider]:
        """Each distinct adapter once — the gateway is registered under several
        names but must be started (and closed) exactly once."""
        seen: list[LLMProvider] = []
        for provider in self._providers.values():
            if not any(provider is existing for existing in seen):
                seen.append(provider)
        return seen


def build_provider_registry(
    *, settings: LaneSettings, catalogue: ModelCatalogue
) -> ProviderRegistry:
    """The one place providers are wired for real (called once, at startup)."""
    registry = ProviderRegistry()

    if settings.lane == "gateway":
        if settings.virtual_keys is None:
            raise ProviderConfigurationError(
                f"{VIRTUAL_KEY_DEFAULT_ENV} is required in the gateway lane — refusing "
                "to boot rather than fall back to the direct lane, which would send "
                "prompts to a different host with a different credential than the "
                "operator configured (C2 §3, ADR-033)"
            )
        gateway = GatewayProvider(
            base_url=settings.gateway_base_url,
            keys=settings.virtual_keys,
            catalogue=catalogue,
        )
        served = catalogue.remote_provider_names()
        if not served:
            raise ProviderConfigurationError(
                "config/models.yaml declares no non-local provider for the gateway "
                "lane to serve"
            )
        for provider_name in served:
            # The SAME instance under every name: one connection pool, one
            # parity check, and a router that cannot tell the lanes apart.
            registry.register(provider_name, gateway)
        return registry

    # ---- direct lane (ADR-033 kill switch) -------------------------------- #
    if settings.anthropic_api_key is not None:
        registry.register(
            "anthropic",
            AnthropicProvider(
                api_key=settings.anthropic_api_key,
                base_url=settings.anthropic_base_url,
                catalogue=catalogue,
            ),
        )
    if settings.openai_api_key is not None:
        registry.register(
            "openai",
            OpenAIProvider(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                catalogue=catalogue,
            ),
        )
    if not registry.provider_names():
        raise ProviderConfigurationError(
            f"{LANE_ENV_VAR}=direct but neither ANTHROPIC_API_KEY nor OPENAI_API_KEY "
            "is set — an empty registry can serve nothing, so this is a boot failure "
            "rather than a 500 on the first turn"
        )
    return registry


async def start_providers(registry: ProviderRegistry) -> None:
    """Run each distinct adapter's startup check exactly once.

    In the gateway lane that is C2 §3's model-parity check (which refuses to
    boot on a drifted alias namespace). The direct lane has no equivalent and
    defines no ``start()`` — its adapters resolve ``provider_model_id:`` per
    entry instead (C2 §3), and that resolution is already validated when
    ``config/models.yaml`` loads.
    """
    for provider in registry.unique_providers():
        start = getattr(provider, "start", None)
        if callable(start):
            await start()


async def close_providers(registry: ProviderRegistry) -> None:
    for provider in registry.unique_providers():
        close = getattr(provider, "aclose", None)
        if callable(close):
            await close()


def registered_provider_names(catalogue: ModelCatalogue) -> Iterable[str]:
    """Convenience for a startup log line: which catalogue providers a gateway
    lane would cover."""
    return catalogue.remote_provider_names()
