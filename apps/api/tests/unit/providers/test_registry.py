"""``providers/registry.py`` — the ONLY module allowed to read the ADR-033 lane
flag, and the place the two lanes are wired.

The properties under test:

* the lane flag selects TRANSPORT WIRING and nothing else — the registry keys
  are the ``config/models.yaml`` provider names in BOTH lanes, so the router
  resolves identically either way (lane-invariance, C2 §2);
* the gateway base URL is validated per ADR-033 (loopback, or the literal
  Compose host ``litellm``, or refuse) and the direct base URLs per ADR-017
  (canonical or loopback);
* in the gateway lane a missing virtual key is a boot failure, not a silent
  fallback to the direct lane (which would send prompts to a different host
  than the operator configured);
* a provider whose key is absent is simply not registered (M1 T25 rule), and
  the resulting gap is a loud, named error at routing time.
"""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.core.routing.errors import ProviderNotRegisteredError
from sunil.providers.anthropic import AnthropicProvider
from sunil.providers.gateway import GatewayProvider
from sunil.providers.openai import OpenAIProvider
from sunil.providers.registry import (
    LANE_ENV_VAR,
    LaneSettings,
    ProviderConfigurationError,
    ProviderRegistry,
    build_provider_registry,
    validate_direct_base_url,
    validate_gateway_base_url,
)
from tests.unit.routing.test_catalogue import repo_root

GATEWAY_ENV = {
    "SUNIL_LLM_GATEWAY_BASE_URL": "http://localhost:4000",
    "LITELLM_VIRTUAL_KEY_DEFAULT": "sk-default",
}


def catalogue() -> ModelCatalogue:
    return ModelCatalogue.load(repo_root() / "config" / "models.yaml")


def registry(env: dict[str, str]) -> ProviderRegistry:
    return build_provider_registry(
        settings=LaneSettings.from_env(env), catalogue=catalogue()
    )


# --------------------------------------------------------------------------- #
# lane selection
# --------------------------------------------------------------------------- #
def test_the_default_lane_is_the_gateway() -> None:
    settings = LaneSettings.from_env(GATEWAY_ENV)

    assert settings.lane == "gateway"
    assert LANE_ENV_VAR == "SUNIL_LLM_PROVIDER_LANE"


def test_an_unknown_lane_value_refuses_to_configure() -> None:
    with pytest.raises(ProviderConfigurationError, match="gateway|direct"):
        LaneSettings.from_env({**GATEWAY_ENV, LANE_ENV_VAR: "whatever"})


def test_gateway_lane_registers_one_gateway_under_every_catalogue_provider_name() -> None:
    """Lane-invariance, mechanically: the router asks for ``anthropic`` and
    ``openai`` because that is what ``config/models.yaml`` says, and in the
    gateway lane BOTH resolve to the single gateway adapter. This is why
    flipping the kill switch needs no router change."""
    built = registry(GATEWAY_ENV)

    assert sorted(built.provider_names()) == ["anthropic", "openai"]
    assert isinstance(built.get("anthropic"), GatewayProvider)
    assert built.get("anthropic") is built.get("openai")  # one client, one pool


def test_direct_lane_registers_the_vendor_adapters_under_the_same_names() -> None:
    built = registry(
        {
            LANE_ENV_VAR: "direct",
            "ANTHROPIC_API_KEY": "sk-ant",
            "OPENAI_API_KEY": "sk-oai",
        }
    )

    assert sorted(built.provider_names()) == ["anthropic", "openai"]
    assert isinstance(built.get("anthropic"), AnthropicProvider)
    assert isinstance(built.get("openai"), OpenAIProvider)


def test_direct_lane_skips_a_provider_whose_key_is_absent() -> None:
    """M1 T25 — a provider with no key is not registered rather than broken; the
    gap surfaces as a named routing error only if something actually routes
    there."""
    built = registry({LANE_ENV_VAR: "direct", "OPENAI_API_KEY": "sk-oai"})

    assert built.provider_names() == ["openai"]
    with pytest.raises(ProviderNotRegisteredError, match="anthropic"):
        built.get("anthropic")


def test_direct_lane_with_no_keys_at_all_refuses_to_configure() -> None:
    """An empty registry can serve nothing: better a boot failure naming the two
    environment variables than a 500 on the first turn."""
    with pytest.raises(ProviderConfigurationError, match="ANTHROPIC_API_KEY"):
        registry({LANE_ENV_VAR: "direct"})


def test_gateway_lane_without_a_virtual_key_refuses_to_boot() -> None:
    """Never a silent fallback to the direct lane: that would send prompts to a
    different host than the operator configured, with a different credential."""
    with pytest.raises(ProviderConfigurationError, match="LITELLM_VIRTUAL_KEY_DEFAULT"):
        registry({"SUNIL_LLM_GATEWAY_BASE_URL": "http://localhost:4000"})


def test_per_agent_virtual_keys_are_read_from_the_environment() -> None:
    settings = LaneSettings.from_env(
        {
            **GATEWAY_ENV,
            "LITELLM_VIRTUAL_KEY_PROJECT_MANAGER": "sk-pm",
            "LITELLM_VIRTUAL_KEY_RESEARCHER": "sk-res",
        }
    )

    assert set(settings.virtual_keys.per_agent) == {"project_manager", "researcher"}
    assert settings.virtual_keys.key_for("project_manager").get_secret_value() == "sk-pm"
    assert settings.virtual_keys.key_for("nobody").get_secret_value() == "sk-default"


def test_lane_settings_never_prints_a_secret() -> None:
    settings = LaneSettings.from_env(
        {**GATEWAY_ENV, "LITELLM_VIRTUAL_KEY_PROJECT_MANAGER": "sk-pm"}
    )

    printed = repr(settings)
    assert "sk-pm" not in printed and "sk-default" not in printed


# --------------------------------------------------------------------------- #
# ADR-033 / ADR-017 base-URL validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:4000",
        "http://127.0.0.1:4000",
        "http://[::1]:4000",
        "http://litellm:4000",
    ],
)
def test_gateway_base_url_accepts_loopback_and_the_compose_host(url: str) -> None:
    assert validate_gateway_base_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example",
        "http://litellm.evil.example:4000",
        "http://10.0.0.5:4000",
        "http://192.168.1.9:4000",
        "http://localhost.evil.example:4000",
        "not-a-url",
    ],
)
def test_gateway_base_url_refuses_everything_else(url: str) -> None:
    """ADR-033's named-host set is a closed, code-level constant: a private-range
    host is NOT admissible (that would be the whole LAN), and ``litellm`` means
    the literal host, not a suffix match."""
    with pytest.raises(ProviderConfigurationError):
        validate_gateway_base_url(url)


def test_building_the_gateway_lane_with_a_hostile_base_url_refuses() -> None:
    with pytest.raises(ProviderConfigurationError):
        registry({**GATEWAY_ENV, "SUNIL_LLM_GATEWAY_BASE_URL": "https://evil.example"})


@pytest.mark.parametrize(
    "url,canonical,ok",
    [
        ("https://api.anthropic.com", "https://api.anthropic.com", True),
        ("http://localhost:9101", "https://api.anthropic.com", True),
        ("http://127.0.0.1:9101", "https://api.anthropic.com", True),
        ("https://api.anthropic.com.evil.example", "https://api.anthropic.com", False),
        ("http://litellm:4000", "https://api.anthropic.com", False),
    ],
)
def test_direct_base_url_is_canonical_or_loopback_only(
    url: str, canonical: str, ok: bool
) -> None:
    """ADR-017 unchanged for the direct lane — and note ``litellm`` is NOT
    admissible here: the named-host extension is scoped to the gateway field."""
    if ok:
        assert validate_direct_base_url(url, canonical=canonical, field="ANTHROPIC_BASE_URL") == url
    else:
        with pytest.raises(ProviderConfigurationError):
            validate_direct_base_url(url, canonical=canonical, field="ANTHROPIC_BASE_URL")


def test_direct_lane_defaults_to_the_canonical_vendor_urls() -> None:
    settings = LaneSettings.from_env({LANE_ENV_VAR: "direct", "OPENAI_API_KEY": "sk-oai"})

    assert settings.anthropic_base_url == "https://api.anthropic.com"
    assert settings.openai_base_url == "https://api.openai.com"


# --------------------------------------------------------------------------- #
# startup
# --------------------------------------------------------------------------- #
async def test_start_providers_runs_the_parity_check_only_in_the_gateway_lane() -> None:
    """C2 §3 — "the direct lane skips this check (its adapters resolve
    ``provider_model_id:`` per entry instead)"."""
    started: list[str] = []

    class Recording(GatewayProvider):
        async def start(self) -> None:  # type: ignore[override]
            started.append(self.name)

    built = ProviderRegistry()
    built.register("anthropic", Recording(base_url="http://localhost:4000", keys=_keys(), catalogue=catalogue()))
    from sunil.providers.registry import start_providers

    await start_providers(built)

    assert started == ["gateway"]


async def test_start_providers_is_a_no_op_for_adapters_without_a_start() -> None:
    from sunil.providers.registry import start_providers

    built = registry({LANE_ENV_VAR: "direct", "OPENAI_API_KEY": "sk-oai"})

    await start_providers(built)  # must not raise


def _keys():
    from sunil.providers.gateway import VirtualKeyring

    return VirtualKeyring(default=SecretStr("sk-default"), per_agent={})
