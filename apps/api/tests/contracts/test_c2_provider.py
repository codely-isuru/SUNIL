"""C2 — Model Provider / Gateway seam contract suite.

Source of truth: ``docs/contracts/C2-model-provider.md`` v1.0.0 (FROZEN
2026-09-10). The six numbered tests of C2 §5 are cited in the docstrings.

Tests 5 and 6 depend on production modules that do not exist yet
(``core/routing/router.py``, ``sunil/settings.py``) and the retry-policy clause
of test 3 depends on ``core/routing/retry.py``. Those clauses skip with a loud
reason; every clause the fake alone can prove is executable here. Debt is
recorded in ``docs/tasks/P0-fakes.md``.
"""

from __future__ import annotations

import json
import re

import pytest

from sunil.providers.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    PrivacyClass,
    ProviderError,
    StreamEvent,
    Usage,
)
from tests.fakes.fake_provider import FIXED_PLAN, FIXED_USAGE, FakeProvider, partition

pytestmark = pytest.mark.contract

PLAN_SCHEMA = {"type": "object", "required": ["intent", "steps"]}


def request(
    message: str,
    *,
    json_schema: dict | None = None,
    privacy_class: PrivacyClass = PrivacyClass.INTERNAL,
) -> CompletionRequest:
    """A CompletionRequest with every C2 §2 field populated.

    Model id is from the frozen gateway alias namespace (C2 §2: exactly
    ``claude-sonnet``, ``claude-opus``, ``claude-haiku``, ``gpt-flagship``,
    ``gpt-mini``); an upstream id here would be a config bug.
    """
    return CompletionRequest(
        model="claude-sonnet",
        messages=[
            ChatMessage(role="system", content="you are a fake"),
            ChatMessage(role="user", content=message),
        ],
        max_tokens=512,
        json_schema=json_schema,
        agent_id="project_manager",
        request_id="req-1",
        privacy_class=privacy_class,
    )


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


# --------------------------------------------------------------------------- #
# C2 contract test 1
# --------------------------------------------------------------------------- #
async def test_c2_1_echo_round_trip(provider: FakeProvider) -> None:
    """C2 contract test 1 — echo round-trip (C2 §5's echo lane: ``text = "FAKE: "
    + <last user message>``, ``parsed=None``), with the fixed usage,
    ``provider_model="fake-1"`` and ``finish_reason="stop"``."""
    result = await provider.complete(request("hello world"))

    assert isinstance(result, CompletionResult)
    assert result.text == "FAKE: hello world"
    assert result.parsed is None
    assert result.provider_model == "fake-1"
    assert result.finish_reason == "stop"
    assert result.usage == Usage(input_tokens=100, output_tokens=25, cost_usd=0.000125)
    assert provider.name == "fake"


async def test_c2_1_usage_sums_across_attempts_including_failures(
    provider: FakeProvider,
) -> None:
    """C2 contract test 1, second clause — usage arithmetic summed across
    attempts INCLUDING failures (C2 §4: tokens burned by failed attempts still
    count, M1 A-2 rule)."""
    attempts: list[Usage] = []

    with pytest.raises(ProviderError) as failure:
        await provider.complete(request("FAIL:invalid_output", json_schema=PLAN_SCHEMA))
    assert failure.value.usage is not None
    attempts.append(failure.value.usage)

    success = await provider.complete(
        request("FAIL:invalid_output", json_schema=PLAN_SCHEMA)
    )
    attempts.append(success.usage)

    assert sum(u.input_tokens for u in attempts) == 200
    assert sum(u.output_tokens for u in attempts) == 50
    assert sum(u.cost_usd for u in attempts) == pytest.approx(0.00025)


# --------------------------------------------------------------------------- #
# C2 contract test 2
# --------------------------------------------------------------------------- #
async def test_c2_2_plan_marker_returns_the_fixed_plan(provider: FakeProvider) -> None:
    """C2 contract test 2 — ``PLAN:`` + schema → ``parsed`` is the fixed plan JSON
    of C2 §5, and ``text`` is its serialisation."""
    result = await provider.complete(
        request("PLAN: close the issue", json_schema=PLAN_SCHEMA)
    )

    assert result.parsed == FIXED_PLAN
    assert json.loads(result.text) == FIXED_PLAN
    # §2's plan-literal rule (THREAT_MODEL §5.1 control 2 / DC-1): every
    # steps[].params value is a literal, with no templating or reference syntax.
    step = result.parsed["steps"][0]
    assert step["params"] == {"key": "demo", "value": "1"}
    assert "{{" not in json.dumps(step)
    assert step["tool"] == "fake_tool" and step["operation"] == "write_item"


async def test_c2_2_plan_without_schema_is_a_programming_error(
    provider: FakeProvider,
) -> None:
    """C2 §5 — the plan lane ``requires json_schema is not None``, else raises
    ``AssertionError("plan requested without schema")``. C2 §2: the plan stage
    always sets ``json_schema``, free-form never plans."""
    with pytest.raises(AssertionError, match="^plan requested without schema$"):
        await provider.complete(request("PLAN: close the issue"))


@pytest.mark.skip(
    reason="C2 contract test 2, second clause — 'parsed validates against the plan "
    "schema' needs core/orchestrator/plan_models.py (Phase 2, core orchestrator). "
    "The fixed-plan shape is asserted above; the schema validation is debt."
)
def test_c2_2_parsed_validates_against_the_real_plan_schema() -> None:
    """C2 contract test 2 — ``parsed`` validates against the plan schema."""


# --------------------------------------------------------------------------- #
# C2 contract test 3
# --------------------------------------------------------------------------- #
async def test_c2_3_invalid_output_raises_once_then_succeeds(
    provider: FakeProvider,
) -> None:
    """C2 contract test 3 — ``FAIL:invalid_output`` + schema → the FIRST call
    raises ``ProviderError(kind="invalid_output")`` whose ``usage`` is counted;
    the SECOND call on the same instance returns the fixed plan (C2 §4: the
    adapter detects and raises, it never re-asks)."""
    with pytest.raises(ProviderError) as err:
        await provider.complete(request("FAIL:invalid_output", json_schema=PLAN_SCHEMA))

    assert err.value.kind == "invalid_output"
    assert err.value.retryable is True
    assert err.value.usage == FIXED_USAGE

    second = await provider.complete(
        request("FAIL:invalid_output", json_schema=PLAN_SCHEMA)
    )
    assert second.parsed == FIXED_PLAN


async def test_c2_3_invalid_output_marker_is_inert_without_a_schema(
    provider: FakeProvider,
) -> None:
    """C2 contract test 3, second clause — ``FAIL:invalid_output`` with
    ``json_schema=None`` → echo lane, no exception (``invalid_output`` is only
    meaningful under a schema; ownership rule, C2 §4)."""
    result = await provider.complete(request("FAIL:invalid_output"))

    assert result.text == "FAKE: FAIL:invalid_output"
    assert result.parsed is None


@pytest.mark.parametrize(
    "marker,kind,retryable",
    [
        ("FAIL:rate_limit", "rate_limit", True),
        ("FAIL:auth", "auth", False),
    ],
)
async def test_c2_3_failure_markers_raise_every_call(
    provider: FakeProvider, marker: str, kind: str, retryable: bool
) -> None:
    """C2 §5 — ``FAIL:rate_limit`` raises on EVERY call (tests count retries);
    ``FAIL:auth`` raises ``retryable=False`` (C2 §4: never retried)."""
    for _ in range(3):
        with pytest.raises(ProviderError) as err:
            await provider.complete(request(marker))
        assert err.value.kind == kind
        assert err.value.retryable is retryable


@pytest.mark.skip(
    reason="C2 contract test 3, retry clause — 'the SUNIL retry policy re-asks "
    "exactly once, then success' needs core/routing/retry.py (Phase 2). The fake's "
    "raise-then-succeed behaviour it drives is asserted above; the policy is debt."
)
def test_c2_3_sunil_retry_policy_re_asks_exactly_once() -> None:
    """C2 contract test 3 — the SUNIL-side re-asker performs at most ONE re-ask."""


# --------------------------------------------------------------------------- #
# C2 contract test 4
# --------------------------------------------------------------------------- #
async def test_c2_4_stream_tokens_partition_the_text_byte_for_byte(
    provider: FakeProvider,
) -> None:
    """C2 contract test 4 — ``stream()`` tokens concatenate to
    ``done.result.text`` BYTE-FOR-BYTE, on a fixture whose text contains a double
    space and a newline (partition property, ADR-027). The leading-whitespace
    clause is asserted on the partition rule itself, below, because the echo lane
    prefixes ``"FAKE: "`` and no provider text can be made to start with
    whitespace through it."""
    message = "  keep  the\nwhitespace   exactly "
    expected = await provider.complete(request(message))
    assert "  " in expected.text and "\n" in expected.text

    events = [event async for event in provider.stream(request(message))]

    assert all(isinstance(event, StreamEvent) for event in events)
    tokens = [event.token for event in events if event.type == "token"]
    done = [event for event in events if event.type == "done"]

    assert "".join(tokens) == expected.text
    assert len(done) == 1
    assert events[-1] is done[0]
    assert done[0].result == expected
    assert done[0].result.model_dump_json() == expected.model_dump_json()
    # The fake's exact partition rule (C2 §5), asserted as the token list itself.
    assert tokens == re.findall(r"\S+\s*|\s+", expected.text)
    assert tokens[0] == "FAKE:   "  # non-whitespace run keeps its trailing whitespace


@pytest.mark.parametrize(
    "text,expected",
    [
        ("  a  b\nc ", ["  ", "a  ", "b\n", "c "]),  # leading run is its own token
        ("plain", ["plain"]),
        ("", []),
        ("\n\n", ["\n\n"]),
        ("trailing ", ["trailing "]),
    ],
)
def test_c2_4_partition_rule_is_whitespace_preserving(
    text: str, expected: list[str]
) -> None:
    """C2 §5 — the exact partition rule ``re.findall(r"\\S+\\s*|\\s+", text)``:
    each maximal non-whitespace run captures its trailing whitespace, a LEADING
    whitespace run is its own token, and joining reproduces ANY text
    byte-for-byte. C5 §4's streaming fake uses this same rule."""
    assert partition(text) == expected
    assert "".join(partition(text)) == text


async def test_c2_4_stream_raises_before_the_first_event_on_failure_markers(
    provider: FakeProvider,
) -> None:
    """C2 §5 — ``FAIL:*`` markers raise BEFORE the first event."""
    seen: list[StreamEvent] = []

    with pytest.raises(ProviderError) as err:
        async for event in provider.stream(request("FAIL:auth")):
            seen.append(event)

    assert err.value.kind == "auth"
    assert seen == []


# --------------------------------------------------------------------------- #
# C2 contract test 5
# --------------------------------------------------------------------------- #
async def test_c2_5_fake_records_every_call_for_the_zero_call_probe(
    provider: FakeProvider,
) -> None:
    """C2 contract test 5's instrumentation — the fake records its calls, so
    'the fake records zero calls' is assertable once the router exists."""
    assert provider.calls == []

    await provider.complete(request("hello"))
    assert len(provider.calls) == 1
    assert provider.calls[0].privacy_class is PrivacyClass.INTERNAL

    with pytest.raises(ProviderError):
        await provider.complete(request("FAIL:auth"))
    assert len(provider.calls) == 2  # a failed attempt is still a call


@pytest.mark.skip(
    reason="C2 contract test 5 — 'LOCAL_ONLY request with no local provider → "
    "routing error raised BEFORE any provider call' needs core/routing/router.py "
    "(Phase 2, SUNIL-owned router). FakeProvider.calls is ready for the zero-call "
    "assertion; the routing rule itself is debt."
)
def test_c2_5_local_only_routes_nowhere_without_a_local_provider() -> None:
    """C2 contract test 5 — a ``LOCAL_ONLY`` request with no local provider is a
    routing error, never a silent downgrade (C2 §2)."""


# --------------------------------------------------------------------------- #
# C2 contract test 6
# --------------------------------------------------------------------------- #
def test_c2_6_gateway_base_url_must_be_loopback_or_the_compose_host() -> None:
    """C2 contract test 6 — ``Settings(sunil_llm_gateway_base_url=
    "https://evil.example")`` refuses to construct (ADR-033: loopback, or the
    literal Compose service host ``litellm``, or the app does not boot)."""
    try:
        from sunil.settings import Settings  # noqa: PLC0415
    except ModuleNotFoundError:
        pytest.skip(
            "C2 contract test 6 needs sunil/settings.py with the ADR-033 validator "
            "(Phase 2 production code). Assertion below is ready."
        )

    with pytest.raises(ValueError):
        Settings(sunil_llm_gateway_base_url="https://evil.example")


# --------------------------------------------------------------------------- #
# C2 §2 — frozen security property of the request model
# --------------------------------------------------------------------------- #
def test_c2_completion_request_has_no_tools_field() -> None:
    """C2 §2 — ``CompletionRequest`` carries NO ``tools`` field. That absence is a
    frozen security property, not an omission: the only path to a tool call is a
    validated plan step through the C1 chokepoint (ROADMAP §25/§33.5), so a
    provider-native tool-calling channel must not exist on this seam.
    """
    assert "tools" not in CompletionRequest.model_fields
    assert "tool_choice" not in CompletionRequest.model_fields
    assert "functions" not in CompletionRequest.model_fields
    assert set(CompletionRequest.model_fields) == {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "json_schema",
        "agent_id",
        "request_id",
        "privacy_class",
    }


def test_c2_completion_request_defaults() -> None:
    """C2 §2 — ``temperature`` defaults to 0.2 and ``json_schema`` to None."""
    built = request("hi")

    assert built.temperature == 0.2
    assert built.json_schema is None
