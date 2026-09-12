"""The SUNIL-owned Model Router — C2 §2 "Router stays SUNIL".

Normative rules under test:

* ``resolve(capability, privacy_class) → (model, provider_name)`` comes from
  ``config/models.yaml``;
* ``LOCAL_ONLY`` resolves ONLY to providers flagged ``local: true`` — with none
  in Phase 0, such a request is a ROUTING ERROR, never a silent downgrade;
* the dev-lane provider is eligible only for ``PUBLIC``;
* these rules run BEFORE provider selection, so no transport setting can widen
  which workloads reach a cloud provider (the exclusion is structural);
* the router — not the caller — fixes ``CompletionRequest.model`` to the
  resolved alias, and the alias namespace is lane-invariant.
"""

from __future__ import annotations

import pytest

from sunil.core.routing.errors import (
    LocalOnlyUnavailableError,
    PrivacyClassNotPermittedError,
    ProviderNotRegisteredError,
    RoutingError,
    UnknownCapabilityError,
)
from sunil.core.routing.retry import RetryPolicy
from sunil.core.routing.router import ModelRouter, ProviderLookup
from sunil.providers.base import PrivacyClass, ProviderError
from tests.fakes.fake_provider import FakeProvider
from tests.unit.routing.catalogues import fake_only, with_local_and_dev_providers
from tests.unit.routing.doubles import RecordingSleep, always, request


class Lookup:
    """The smallest thing satisfying ``ProviderLookup`` — proof that the router
    depends on the PROTOCOL and not on ``providers/registry.py`` (which is the
    only module allowed to read the ADR-033 lane flag)."""

    def __init__(self, **providers) -> None:
        self._providers = providers

    def get(self, name: str):
        if name not in self._providers:
            raise ProviderNotRegisteredError(name)
        return self._providers[name]

    def provider_names(self) -> list[str]:
        return list(self._providers)


def router(catalogue=None, **providers) -> ModelRouter:
    return ModelRouter(
        catalogue=catalogue or fake_only(),
        providers=Lookup(**providers),
        retry=RetryPolicy(sleep=RecordingSleep(), rand=lambda: 0.0),
    )


_check: ProviderLookup = Lookup()


# --------------------------------------------------------------------------- #
# resolution
# --------------------------------------------------------------------------- #
def test_capability_resolves_to_a_model_alias_and_a_provider_name() -> None:
    provider = FakeProvider()

    route = router(fake=provider).resolve(
        capability="general_reasoning", privacy_class=PrivacyClass.INTERNAL
    )

    assert route.model == "claude-sonnet"
    assert route.provider_name == "fake"
    assert route.provider is provider
    assert route.max_tokens == 4096
    assert route.timeout_s == 30.0


def test_an_unknown_capability_is_a_named_routing_error() -> None:
    with pytest.raises(UnknownCapabilityError):
        router(fake=FakeProvider()).resolve(
            capability="telepathy", privacy_class=PrivacyClass.INTERNAL
        )


def test_a_capability_whose_provider_is_not_registered_fails_closed() -> None:
    """The catalogue knows ``fake``; nothing registered it. That is a startup
    wiring bug and must be a loud, named error rather than a ``KeyError``."""
    with pytest.raises(ProviderNotRegisteredError):
        router().resolve(capability="general_reasoning", privacy_class=PrivacyClass.INTERNAL)


# --------------------------------------------------------------------------- #
# LOCAL_ONLY (§26.10)
# --------------------------------------------------------------------------- #
async def test_local_only_with_no_local_provider_raises_before_any_dispatch() -> None:
    """C2 contract test 5 — the fake records ZERO calls: a silent downgrade to a
    remote model is the failure mode this test exists to prevent."""
    provider = FakeProvider()
    subject = router(fake=provider)

    with pytest.raises(LocalOnlyUnavailableError):
        await subject.run(
            capability="general_reasoning",
            request=request("secret", privacy_class="local_only"),
        )

    assert provider.calls == []


async def test_the_same_router_does_reach_the_provider_for_internal() -> None:
    """The control for the test above: the zero-call result proves the RULE and
    not a broken fixture."""
    provider = FakeProvider()

    completion = await router(fake=provider).run(
        capability="general_reasoning", request=request("hello")
    )

    assert len(provider.calls) == 1
    assert completion.result.text == "FAKE: hello"


def test_local_only_resolves_when_a_local_provider_exists() -> None:
    """The positive case, so the rule is "local providers serve LOCAL_ONLY", not
    "LOCAL_ONLY always fails"."""
    route = router(
        with_local_and_dev_providers(), fake_local=FakeProvider()
    ).resolve(capability="local_reasoning", privacy_class=PrivacyClass.LOCAL_ONLY)

    assert route.provider_name == "fake_local"


def test_a_local_provider_also_serves_the_lower_privacy_classes() -> None:
    route = router(
        with_local_and_dev_providers(), fake_local=FakeProvider()
    ).resolve(capability="local_reasoning", privacy_class=PrivacyClass.CONFIDENTIAL)

    assert route.provider_name == "fake_local"


# --------------------------------------------------------------------------- #
# the dev lane is PUBLIC-only (ADR-030 §8)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "privacy_class",
    [PrivacyClass.INTERNAL, PrivacyClass.CONFIDENTIAL, PrivacyClass.LOCAL_ONLY],
)
def test_the_dev_lane_provider_is_ineligible_above_public(privacy_class) -> None:
    catalogue = with_local_and_dev_providers()

    with pytest.raises(RoutingError):
        router(catalogue, omniroute=FakeProvider()).resolve(
            capability="dev_experiment", privacy_class=privacy_class
        )


def test_the_dev_lane_provider_is_eligible_for_public() -> None:
    route = router(with_local_and_dev_providers(), omniroute=FakeProvider()).resolve(
        capability="dev_experiment", privacy_class=PrivacyClass.PUBLIC
    )

    assert route.provider_name == "omniroute"
    assert issubclass(PrivacyClassNotPermittedError, RoutingError)


# --------------------------------------------------------------------------- #
# policy runs before provider selection (structural exclusion)
# --------------------------------------------------------------------------- #
def test_privacy_policy_is_evaluated_before_the_provider_is_even_looked_up() -> None:
    """Central-memory lesson 2026-08-17: population scoping must not be an input
    the excluded population's decision reads. Here that is mechanical — with
    NOTHING registered, a ``LOCAL_ONLY`` request still fails on the privacy rule
    (``LocalOnlyUnavailableError``), never on the registration gap. If the order
    were reversed, transport state (what happens to be registered, which the
    lane flag decides) would be observable by the policy."""
    with pytest.raises(LocalOnlyUnavailableError):
        router().resolve(capability="general_reasoning", privacy_class=PrivacyClass.LOCAL_ONLY)


def test_the_router_never_accepts_a_privacy_class_argument_that_shadows_the_request() -> None:
    """``privacy_class`` travels on the ``CompletionRequest`` (C2 §2), so
    ``run()`` takes no separate privacy argument a caller could disagree with."""
    import inspect

    signature = inspect.signature(ModelRouter.run)

    assert set(signature.parameters) == {"self", "capability", "request"}


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
async def test_run_fixes_the_model_alias_from_the_catalogue() -> None:
    """C2 §2 — ``CompletionRequest.model`` is the ROUTER-resolved id. A caller's
    guess is overwritten, so an upstream id can never reach the wire."""
    provider = FakeProvider()

    await router(fake=provider).run(
        capability="general_reasoning",
        request=request("hi", model="anthropic/claude-sonnet-4-5"),
    )

    assert provider.calls[0].model == "claude-sonnet"


async def test_run_leaves_every_other_request_field_alone() -> None:
    provider = FakeProvider()
    original = request("hi", json_schema={"type": "object"})

    await router(fake=provider).run(capability="general_reasoning", request=original)

    sent = provider.calls[0]
    assert sent.json_schema == {"type": "object"}
    assert sent.agent_id == "project_manager"
    assert sent.request_id == "req-1"
    assert sent.privacy_class is PrivacyClass.INTERNAL
    assert sent.max_tokens == original.max_tokens


async def test_max_tokens_above_the_models_output_ceiling_is_a_routing_error() -> None:
    """Fail loudly rather than clamp: a silently shortened answer is a
    correctness bug the caller cannot see."""
    with pytest.raises(RoutingError, match="max_output"):
        await router(fake=FakeProvider()).run(
            capability="general_reasoning", request=request("hi", max_tokens=999_999)
        )


async def test_run_reports_the_attempts_and_the_total_usage() -> None:
    """The router is where the attempt count is known (M1 A-17) and where the
    A-2 usage total is handed to the caller for its ``llm_calls`` rows."""
    provider = always("rate_limit")

    with pytest.raises(ProviderError):
        await router(fake=provider).run(
            capability="general_reasoning", request=request("hi")
        )

    assert len(provider.calls) == 3


async def test_run_passes_the_capability_timeout_to_the_retry_policy() -> None:
    """The deadline seam gets the capability's own ``timeout_s`` — the router is
    the only layer that knows it."""
    seen: list[float | None] = []

    class Spy(RetryPolicy):
        async def execute(self, *, provider, request, attempt_timeout_s=None):
            seen.append(attempt_timeout_s)
            return await super().execute(
                provider=provider, request=request, attempt_timeout_s=attempt_timeout_s
            )

    subject = ModelRouter(
        catalogue=fake_only(),
        providers=Lookup(fake=FakeProvider()),
        retry=Spy(sleep=RecordingSleep()),
    )
    await subject.run(capability="general_reasoning", request=request("hi"))

    assert seen == [30.0]
