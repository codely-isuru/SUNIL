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
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from sunil.providers.base import (
    GATEWAY_MODEL_ALIASES,
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


def missing(module: str, what: str, owner: str):
    """Import ``module`` or skip with a loud, self-activating reason.

    The pattern (C1's ``tool_manager_class()``) replaces the bare
    ``@pytest.mark.skip`` decorators of the fakes-build round, which sat on empty
    bodies and would have kept skipping FOREVER — silently, long after the
    module they waited for had landed (QA finding F5). An import guard flips to
    executing the moment the module exists.
    """
    from importlib import import_module  # noqa: PLC0415

    try:
        return import_module(module)
    except ModuleNotFoundError:
        pytest.skip(f"{what} needs {module} ({owner}). This test activates when it lands.")


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


async def test_c2_2_parsed_validates_against_the_real_plan_schema(
    provider: FakeProvider,
) -> None:
    """C2 contract test 2, second clause — ``parsed`` validates against the REAL
    plan schema (not just the fixed-plan shape asserted above).

    Guarded on ``core/orchestrator/plan_models.py`` (Phase 2, core orchestrator).
    The body is written against the one thing the contract does fix: whatever
    that module exports as ``Plan`` must accept C2 §5's fixed plan — if the fake
    the whole suite plans with cannot validate, either the fake or the schema is
    wrong, and this is where that shows up.
    """
    plan_models = missing(
        "sunil.core.orchestrator.plan_models",
        "C2 contract test 2's schema-validation clause",
        "Phase 2, core orchestrator",
    )
    plan_model = getattr(plan_models, "Plan", None)
    assert plan_model is not None, (
        "plan_models.py exists but exports no `Plan` — C2 test 2 needs the plan "
        "model to validate a planned turn against"
    )

    result = await provider.complete(request("PLAN: go", json_schema=PLAN_SCHEMA))
    validated = plan_model.model_validate(result.parsed)

    assert validated.steps[0].tool == "fake_tool"
    assert validated.steps[0].operation == "write_item"
    assert validated.steps[0].params == {"key": "demo", "value": "1"}


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


def test_c2_3_sunil_retry_policy_re_asks_exactly_once() -> None:
    """C2 contract test 3, retry clause — the SUNIL-side re-asker performs at
    most ONE re-ask.

    Guarded on ``core/routing/retry.py``. The assertions are named below rather
    than written: C2 §4 fixes the POLICY (one re-ask on ``invalid_output``, then
    fail; the flag marks eligibility, the policy caps the count) but names no
    callable, and QA inventing an entry point here would hard-code an API the
    implementer has not chosen. This fails loudly the moment the module lands —
    it can never sit green having asserted nothing.
    """
    missing("sunil.core.routing.retry", "C2 contract test 3's retry clause", "Phase 2, core")
    pytest.fail(
        "core/routing/retry.py now exists — write this test: drive a FakeProvider "
        "whose last user message is 'FAIL:invalid_output' (raises once, then "
        "succeeds) through the policy with json_schema set, then assert "
        "len(provider.calls) == 2 (exactly ONE re-ask), that the second call "
        "returns FIXED_PLAN, and that a provider raising invalid_output on EVERY "
        "call produces exactly 2 calls and then a ProviderError — never a third."
    )


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


def test_c2_5_local_only_routes_nowhere_without_a_local_provider() -> None:
    """C2 contract test 5 — a ``LOCAL_ONLY`` request with no local provider is a
    routing error, never a silent downgrade (C2 §2).

    Guarded on ``core/routing/router.py`` (Phase 2, SUNIL-owned router). Same
    reasoning as the retry clause: the rule is frozen, the router's constructor
    and method names are not, and the zero-call instrumentation this needs is
    already asserted in
    ``test_c2_5_fake_records_every_call_for_the_zero_call_probe``.
    """
    missing("sunil.core.routing.router", "C2 contract test 5's routing rule", "Phase 2, core")
    pytest.fail(
        "core/routing/router.py now exists — write this test: build the router "
        "with a single non-local FakeProvider, submit a request with "
        "privacy_class=LOCAL_ONLY, assert it RAISES before dispatch and that "
        "provider.calls == [] (a silent downgrade to a remote model is the "
        "failure mode; §26.10). Then assert an INTERNAL request through the same "
        "router does reach the provider, so the zero-call proves the rule and "
        "not a broken fixture."
    )


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


@pytest.mark.parametrize(
    "model,kwargs",
    [
        (CompletionRequest, {"tools": [{"name": "x"}]}),
        (CompletionRequest, {"tool_choice": "auto"}),
        (ChatMessage, {"tool_calls": []}),
        (Usage, {"reasoning_tokens": 5}),
        (CompletionResult, {"tool_calls": []}),
        (StreamEvent, {"delta": "x"}),
    ],
    ids=[
        "request-tools",
        "request-tool_choice",
        "message-tool_calls",
        "usage-extra",
        "result-tool_calls",
        "stream-extra",
    ],
)
def test_c2_7_every_section_2_model_is_closed(model, kwargs: dict) -> None:
    """C2 contract test 7 (v1.0.1, backend review F11) — every §2 request/result
    model sets ``extra="forbid"``, so an undeclared field raises
    ``ValidationError`` AT THE CALL SITE instead of being silently dropped.

    Under pydantic's default ``extra="ignore"``, ``CompletionRequest(...,
    tools=[...])`` constructed happily and threw the tools away: the frozen
    no-tools property still held, but it eroded SILENTLY — a call site could
    believe it had sent tools forever. The message list is the same smuggling
    channel (``ChatMessage(..., tool_calls=[...])``), which is why the rule
    covers all five models and not just the request.
    """
    valid = {
        CompletionRequest: dict(
            model="claude-sonnet",
            messages=[ChatMessage(role="user", content="hi")],
            max_tokens=512,
            agent_id="project_manager",
            request_id="req-1",
            privacy_class=PrivacyClass.INTERNAL,
        ),
        ChatMessage: dict(role="assistant", content="hi"),
        Usage: dict(input_tokens=1, output_tokens=1, cost_usd=0.0),
        CompletionResult: dict(
            text="t",
            parsed=None,
            usage=Usage(input_tokens=1, output_tokens=1, cost_usd=0.0),
            provider_model="fake-1",
            finish_reason="stop",
        ),
        StreamEvent: dict(type="token", token="x"),
    }[model]

    assert model(**valid)  # the same kwargs without the extra field are legal
    with pytest.raises(ValidationError):
        model(**valid, **kwargs)


@pytest.mark.parametrize(
    "model",
    [ChatMessage, CompletionRequest, Usage, CompletionResult, StreamEvent],
    ids=lambda m: m.__name__,
)
def test_c2_7_closed_is_declared_not_incidental(model) -> None:
    """C2 §2 (v1.0.1) — the property is normative, so it is asserted on the
    model config itself: a future §2 model that forgets ``_ClosedModel`` (or a
    per-model ``model_config``) fails here rather than in whichever call site
    first smuggles a field past it."""
    assert model.model_config.get("extra") == "forbid"


def test_c2_completion_request_defaults() -> None:
    """C2 §2 — ``temperature`` defaults to 0.2 and ``json_schema`` to None."""
    built = request("hi")

    assert built.temperature == 0.2
    assert built.json_schema is None


# --------------------------------------------------------------------------- #
# C2 §5 — the fake must not hand out shared module state (backend review F1)
# --------------------------------------------------------------------------- #
async def test_c2_fake_results_never_alias_the_modules_fixed_constants(
    provider: FakeProvider,
) -> None:
    """Backend review **F1** — the fake returned ``FIXED_PLAN`` and
    ``FIXED_USAGE`` BY IDENTITY, so any consumer that mutated a result rewrote
    the fixture for the whole process: the next test in the same session gets a
    plan someone else edited. The C2 §5 fake is specified as deterministic, and
    "deterministic" cannot survive a caller.

    Every assertion below compares against a pristine snapshot taken before the
    mutation, never against the module constants themselves — comparing to the
    constants is exactly the assertion that passes while both sides rot.
    """
    pristine_plan = deepcopy(FIXED_PLAN)
    pristine_usage = FIXED_USAGE.model_copy(deep=True)

    first = await provider.complete(request("PLAN: go", json_schema=PLAN_SCHEMA))
    assert first.parsed is not FIXED_PLAN
    assert first.usage is not FIXED_USAGE

    # A consumer does what consumers do.
    first.parsed["intent"] = "hijacked"
    first.parsed["steps"][0]["params"]["key"] = "mutated"
    first.usage.input_tokens = 999

    # The module fixtures are untouched...
    assert FIXED_PLAN == pristine_plan
    assert FIXED_USAGE == pristine_usage

    # ...and so is the next call, including nested params (a shallow copy of the
    # plan would share `steps[0]["params"]` and fail here).
    second = await provider.complete(request("PLAN: go", json_schema=PLAN_SCHEMA))
    assert second.parsed == pristine_plan
    assert second.parsed is not first.parsed
    assert second.usage == pristine_usage

    # The echo lane hands out the same usage object in the frozen spec.
    echo = await provider.complete(request("hello"))
    assert echo.usage is not FIXED_USAGE
    echo.usage.cost_usd = 42.0
    assert FIXED_USAGE == pristine_usage


# --------------------------------------------------------------------------- #
# C2 §2 — the frozen gateway alias namespace (QA nit F9: it was untested)
# --------------------------------------------------------------------------- #
def contract_text() -> str:
    """``docs/contracts/C2-model-provider.md``, located by walking up."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "docs" / "contracts" / "C2-model-provider.md"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise AssertionError("C2-model-provider.md not found above this test file")


def test_c2_gateway_model_aliases_match_the_contracts_frozen_namespace() -> None:
    """C2 §2 — ``config/models.yaml`` ids MUST equal the LiteLLM gateway's
    ``model_name`` alias set verbatim: at Phase 0 exactly ``claude-sonnet``,
    ``claude-opus``, ``claude-haiku``, ``gpt-flagship``, ``gpt-mini``.

    Nit F9 disposition: the constant stays in ``providers/base.py`` (the module
    every provider adapter already imports, and where the startup parity check
    will read it), but it is no longer untested — a second source of truth that
    nothing checks is worse than no constant at all. The assertion is against
    the CONTRACT TEXT, not a copy of the list: if the frozen namespace changes,
    this fails rather than agreeing with a stale constant.
    """
    text = contract_text()
    quoted = {
        alias
        for alias in ("claude-sonnet", "claude-opus", "claude-haiku", "gpt-flagship", "gpt-mini")
        if f"`{alias}`" in text
    }

    assert quoted == set(GATEWAY_MODEL_ALIASES), (
        "GATEWAY_MODEL_ALIASES disagrees with C2 §2's frozen alias namespace"
    )
    assert len(GATEWAY_MODEL_ALIASES) == 5
    assert isinstance(GATEWAY_MODEL_ALIASES, tuple)  # not a mutable module global
    # An upstream provider id must never appear in the namespace (C2 §2: those
    # live only inside the gateway config and in CompletionResult.provider_model).
    assert not [alias for alias in GATEWAY_MODEL_ALIASES if "/" in alias]
    # ...and the request fixture this whole suite uses names one of them.
    assert request("hi").model in GATEWAY_MODEL_ALIASES
