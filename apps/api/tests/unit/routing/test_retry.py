"""The SUNIL-side retry policy — C2 §4 "Retry ownership".

The normative rules under test:

* there is exactly ONE retry layer and it is SUNIL's (the gateway runs
  ``num_retries: 0``); the adapter detects and raises, it never re-asks;
* ``invalid_output`` gets at most ONE re-ask, then the failure surfaces;
* ``retryable=True`` marks ELIGIBILITY — the policy, not the flag, caps the
  count (so a flag of ``False`` is still honoured as "not eligible");
* usage accumulates across attempts INCLUDING failures (M1 A-2 rule);
* an attempt that cannot fit the remaining turn deadline is never started.
"""

from __future__ import annotations

import pytest

from sunil.core.routing.retry import (
    MAX_ATTEMPTS,
    RetryPolicy,
    TurnDeadlineExceeded,
    backoff_seconds,
)
from sunil.providers.base import ProviderError
from tests.fakes.fake_provider import FIXED_PLAN, FakeProvider
from tests.unit.routing.doubles import (
    RecordingSleep,
    ScriptedProvider,
    always,
    failing_then_ok,
    ok,
    request,
)

PLAN_SCHEMA = {"type": "object", "required": ["intent", "steps"]}


def policy(**kwargs) -> RetryPolicy:
    """A policy whose sleeping is recorded rather than performed."""
    kwargs.setdefault("sleep", RecordingSleep())
    kwargs.setdefault("rand", lambda: 1.0)  # full jitter at its maximum draw
    return RetryPolicy(**kwargs)


# --------------------------------------------------------------------------- #
# the happy path
# --------------------------------------------------------------------------- #
async def test_a_successful_call_is_one_attempt_and_no_sleep() -> None:
    sleep = RecordingSleep()
    provider = ScriptedProvider([ok("hi")])

    outcome = await policy(sleep=sleep).execute(provider=provider, request=request())

    assert outcome.result.text == "hi"
    assert len(provider.calls) == 1
    assert len(outcome.attempts) == 1
    assert outcome.attempts[0].error_kind is None
    assert sleep.slept == []
    assert outcome.usage.input_tokens == 100


# --------------------------------------------------------------------------- #
# invalid_output — exactly one re-ask (C2 §4)
# --------------------------------------------------------------------------- #
async def test_invalid_output_is_re_asked_exactly_once_then_succeeds() -> None:
    """The FakeProvider is the contract's own instrument: ``FAIL:invalid_output``
    raises on the first call and returns the fixed plan on the second."""
    provider = FakeProvider()

    outcome = await policy().execute(
        provider=provider,
        request=request("FAIL:invalid_output", json_schema=PLAN_SCHEMA),
    )

    assert len(provider.calls) == 2  # ONE re-ask
    assert outcome.result.parsed == FIXED_PLAN
    # M1 A-2: the burnt tokens of the failed attempt are in the total.
    assert outcome.usage.input_tokens == 200
    assert outcome.usage.output_tokens == 50
    assert outcome.usage.cost_usd == pytest.approx(0.00025)
    assert [a.error_kind for a in outcome.attempts] == ["invalid_output", None]


async def test_invalid_output_on_every_call_produces_two_calls_and_then_fails() -> None:
    """Never a third: the policy caps the re-ask at one and surfaces the
    failure, which the orchestrator turns into ``plan_rejected`` on the PLAN
    stage."""
    provider = always("invalid_output")

    with pytest.raises(ProviderError) as err:
        await policy().execute(
            provider=provider, request=request("go", json_schema=PLAN_SCHEMA)
        )

    assert len(provider.calls) == 2
    assert err.value.kind == "invalid_output"
    # Terminal: the caller must not retry what the policy already exhausted.
    assert err.value.retryable is False
    # The surfaced error carries the total burn of BOTH attempts (A-2).
    assert err.value.usage is not None
    assert err.value.usage.input_tokens == 200
    assert isinstance(err.value.__cause__, ProviderError)


async def test_a_re_ask_does_not_sleep() -> None:
    """An ``invalid_output`` re-ask is not a rate-limit backoff: re-asking the
    same model immediately is the point, and a 1-4 s sleep inside the turn
    deadline buys nothing."""
    sleep = RecordingSleep()
    provider = FakeProvider()

    await policy(sleep=sleep).execute(
        provider=provider, request=request("FAIL:invalid_output", json_schema=PLAN_SCHEMA)
    )

    assert sleep.slept == []


# --------------------------------------------------------------------------- #
# transient kinds
# --------------------------------------------------------------------------- #
async def test_rate_limit_is_retried_up_to_the_attempt_budget_with_backoff() -> None:
    sleep = RecordingSleep()
    provider = always("rate_limit")

    with pytest.raises(ProviderError) as err:
        await policy(sleep=sleep).execute(provider=provider, request=request())

    assert len(provider.calls) == MAX_ATTEMPTS == 3
    assert err.value.kind == "rate_limit"
    # Full jitter at rand()==1.0 → the bases themselves, before attempts 2 and 3.
    assert sleep.slept == [1.0, 2.0]


async def test_overloaded_recovers_on_the_second_attempt() -> None:
    provider = failing_then_ok("overloaded")

    outcome = await policy().execute(provider=provider, request=request())

    assert len(provider.calls) == 2
    assert outcome.result.text == "ok"
    assert [a.error_kind for a in outcome.attempts] == ["overloaded", None]


async def test_timeout_is_retried_exactly_once() -> None:
    """C2 §4 — ``timeout``: "retried once". A read timeout usually means the
    request is still being served upstream; hammering it triples the spend."""
    provider = always("timeout", usage=None)

    with pytest.raises(ProviderError) as err:
        await policy().execute(provider=provider, request=request())

    assert len(provider.calls) == 2
    assert err.value.kind == "timeout"
    # usage=None on every attempt must not become a None total.
    assert err.value.usage is not None
    assert err.value.usage.input_tokens == 0


# --------------------------------------------------------------------------- #
# terminal kinds
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind", ["auth", "bad_request", "budget_exceeded"])
async def test_terminal_kinds_are_never_retried(kind: str) -> None:
    provider = always(kind, retryable=False)

    with pytest.raises(ProviderError) as err:
        await policy().execute(provider=provider, request=request())

    assert len(provider.calls) == 1
    assert err.value.kind == kind
    # A single-attempt failure surfaces the ADAPTER'S OWN exception object, not
    # a re-wrapped copy: nothing was accumulated, so nothing needs rewriting,
    # and the traceback points at the adapter that classified it.
    assert err.value.__cause__ is None
    assert err.value.usage is not None and err.value.usage.input_tokens == 100


async def test_a_retryable_flag_of_false_is_honoured_even_for_a_retryable_kind() -> None:
    """C2 §4 — the flag marks eligibility. An adapter that knows THIS rate-limit
    is hopeless (a key-level budget stop, say) says so, and the policy obeys."""
    provider = always("rate_limit", retryable=False)

    with pytest.raises(ProviderError):
        await policy().execute(provider=provider, request=request())

    assert len(provider.calls) == 1


async def test_a_non_provider_exception_is_never_retried() -> None:
    """``AssertionError`` (the fake's "plan requested without schema") is a
    programming error: retrying it would just run the bug three times."""
    provider = FakeProvider()

    with pytest.raises(AssertionError):
        await policy().execute(provider=provider, request=request("PLAN: go"))

    assert len(provider.calls) == 1


# --------------------------------------------------------------------------- #
# the turn deadline
# --------------------------------------------------------------------------- #
async def test_an_attempt_that_cannot_fit_the_deadline_is_never_started() -> None:
    """M1 §5.3, ported: "a retry that cannot finish is not a retry, it is a way
    to blow the latency budget quietly"."""
    provider = ScriptedProvider([ok()])

    with pytest.raises(TurnDeadlineExceeded) as err:
        await policy(remaining_deadline_s=lambda: 2.0).execute(
            provider=provider, request=request(), attempt_timeout_s=30.0
        )

    assert provider.calls == []
    assert err.value.remaining_s == 2.0
    assert err.value.needed_s == 30.0


async def test_the_deadline_is_re_checked_before_the_retry_not_only_at_the_start() -> None:
    remaining = [30.0, 1.0]  # the first attempt fits, the retry does not
    provider = always("rate_limit")

    with pytest.raises(TurnDeadlineExceeded):
        await policy(remaining_deadline_s=lambda: remaining.pop(0)).execute(
            provider=provider, request=request(), attempt_timeout_s=10.0
        )

    assert len(provider.calls) == 1


async def test_no_deadline_seam_means_no_deadline_check() -> None:
    """The policy is usable before the orchestrator's trace context exists —
    the seam defaults to absent rather than to a made-up budget."""
    provider = ScriptedProvider([ok()])

    outcome = await policy().execute(
        provider=provider, request=request(), attempt_timeout_s=999.0
    )

    assert outcome.result.text == "ok"


# --------------------------------------------------------------------------- #
# backoff primitive
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "failed_attempts,base", [(0, 1.0), (1, 1.0), (2, 2.0), (3, 4.0), (9, 4.0)]
)
def test_backoff_bases_are_one_two_four_with_full_jitter(
    failed_attempts: int, base: float
) -> None:
    assert backoff_seconds(failed_attempts, rand=lambda: 1.0) == base
    assert backoff_seconds(failed_attempts, rand=lambda: 0.0) == 0.0
    assert backoff_seconds(failed_attempts, rand=lambda: 0.5) == base / 2


# --------------------------------------------------------------------------- #
# the request is never mutated
# --------------------------------------------------------------------------- #
async def test_every_attempt_sends_the_same_request_object_unmutated() -> None:
    """A re-ask must not quietly edit the prompt (append "try again", say):
    the audit spine's promise is that what we logged is what we sent."""
    provider = failing_then_ok("rate_limit")
    original = request("hello", json_schema=PLAN_SCHEMA)
    snapshot = original.model_dump_json()

    await policy().execute(provider=provider, request=original)

    assert [call.model_dump_json() for call in provider.calls] == [snapshot, snapshot]
    assert original.model_dump_json() == snapshot
