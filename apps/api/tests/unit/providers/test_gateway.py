"""``providers/gateway.py`` — the DEFAULT lane (C2 §3).

Every test drives the real adapter over an ``httpx.MockTransport``: the wire
shape, the auth header, the error classification and the structured-output
validator are all asserted on the bytes the adapter would have sent, with no
network and no key. That is ADR-017's test-seam pattern applied to a gateway —
``base_url`` is injected, never read from the environment by this module.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.providers.base import (
    GATEWAY_MODEL_ALIASES,
    ChatMessage,
    CompletionRequest,
    GatewayModelParityError,
    LLMProvider,
    PrivacyClass,
    ProviderError,
)
from sunil.providers.gateway import GatewayProvider, VirtualKeyring
from tests.unit.routing.test_catalogue import repo_root

BASE_URL = "http://localhost:4000"
PLAN_SCHEMA = {"type": "object", "required": ["intent", "steps"]}


def catalogue() -> ModelCatalogue:
    return ModelCatalogue.load(repo_root() / "config" / "models.yaml")


def keyring(**per_agent: str) -> VirtualKeyring:
    return VirtualKeyring(
        default=SecretStr("sk-default-virtual-key"),
        per_agent={agent: SecretStr(key) for agent, key in per_agent.items()},
    )


def request(
    message: str = "hello",
    *,
    model: str = "claude-sonnet",
    json_schema: dict | None = None,
    agent_id: str = "project_manager",
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content="be brief"),
            ChatMessage(role="user", content=message),
        ],
        max_tokens=512,
        json_schema=json_schema,
        agent_id=agent_id,
        request_id="req-42",
        privacy_class=PrivacyClass.INTERNAL,
    )


def completion_body(
    *, content: str = "hi there", tokens: tuple[int, int] = (100, 25), finish: str = "stop"
) -> dict:
    """A minimal OpenAI-compatible chat-completion response, as LiteLLM returns
    it (verified live against the pinned proxy on 2026-09-11 for ``/v1/models``;
    this body is the documented chat-completions shape)."""
    return {
        "id": "chatcmpl-x",
        "object": "chat.completion",
        "model": "claude-sonnet-4-5",
        "choices": [
            {"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}
        ],
        "usage": {"prompt_tokens": tokens[0], "completion_tokens": tokens[1]},
    }


def provider(
    handler, *, keys: VirtualKeyring | None = None, base_url: str = BASE_URL
) -> GatewayProvider:
    return GatewayProvider(
        base_url=base_url,
        keys=keys or keyring(),
        catalogue=catalogue(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def responder(body: dict, status: int = 200):
    seen: list[httpx.Request] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        seen.append(sent)
        return httpx.Response(status, json=body)

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


_check: LLMProvider = GatewayProvider(
    base_url=BASE_URL, keys=keyring(), catalogue=catalogue()
)


# --------------------------------------------------------------------------- #
# the wire
# --------------------------------------------------------------------------- #
async def test_complete_posts_openai_compatible_chat_completions() -> None:
    handler = responder(completion_body())

    result = await provider(handler).complete(request())

    sent = handler.seen[0]
    assert sent.method == "POST"
    assert str(sent.url) == f"{BASE_URL}/v1/chat/completions"
    body = json.loads(sent.content)
    assert body["model"] == "claude-sonnet"  # the ALIAS, never an upstream id
    assert body["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hello"},
    ]
    assert body["max_tokens"] == 512
    assert body["temperature"] == 0.2
    assert result.text == "hi there"
    assert result.finish_reason == "stop"


async def test_the_request_body_never_carries_a_tools_field() -> None:
    """C2 §2's frozen security property, asserted on the BYTES: the only path to
    a tool call is a validated plan step through the C1 chokepoint, so no
    provider-native tool channel may appear on this seam — not even an empty
    one, which some providers treat as "tools allowed"."""
    handler = responder(completion_body(content=json.dumps({"intent": "x", "steps": []})))

    await provider(handler).complete(request(json_schema=PLAN_SCHEMA))

    body = json.loads(handler.seen[0].content)
    assert set(body) <= {
        "model",
        "messages",
        "max_tokens",
        "temperature",
        "response_format",
        "metadata",
        "stream",
        "stream_options",
    }
    for forbidden in ("tools", "tool_choice", "functions", "function_call"):
        assert forbidden not in body


async def test_metadata_carries_the_correlation_ids_and_the_prompt_does_not() -> None:
    """C2 §2/§3 — ``request_id`` is forwarded as metadata so gateway logs and
    ``llm_calls`` rows correlate, and NEVER in the prompt."""
    handler = responder(completion_body())

    await provider(handler).complete(request())

    body = json.loads(handler.seen[0].content)
    assert body["metadata"] == {"request_id": "req-42", "agent_id": "project_manager"}
    assert "req-42" not in json.dumps(body["messages"])


async def test_structured_output_sets_response_format_json_schema() -> None:
    handler = responder(completion_body(content=json.dumps({"intent": "x", "steps": []})))

    result = await provider(handler).complete(request(json_schema=PLAN_SCHEMA))

    body = json.loads(handler.seen[0].content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["schema"] == PLAN_SCHEMA
    assert result.parsed == {"intent": "x", "steps": []}


async def test_no_response_format_when_no_schema_was_asked_for() -> None:
    handler = responder(completion_body())

    result = await provider(handler).complete(request())

    assert "response_format" not in json.loads(handler.seen[0].content)
    assert result.parsed is None


# --------------------------------------------------------------------------- #
# virtual keys (C2 §3)
# --------------------------------------------------------------------------- #
async def test_the_per_agent_virtual_key_is_preferred_over_the_default() -> None:
    handler = responder(completion_body())
    keys = keyring(project_manager="sk-pm-key")

    await provider(handler, keys=keys).complete(request(agent_id="project_manager"))

    assert handler.seen[0].headers["authorization"] == "Bearer sk-pm-key"


async def test_the_default_virtual_key_is_used_for_an_agent_without_one() -> None:
    handler = responder(completion_body())

    await provider(handler, keys=keyring(project_manager="sk-pm-key")).complete(
        request(agent_id="researcher")
    )

    assert handler.seen[0].headers["authorization"] == "Bearer sk-default-virtual-key"


def test_the_keyring_never_exposes_a_key_through_repr() -> None:
    """ADR-006 — keys are ``SecretStr``; a stray ``repr()`` in a log or a
    traceback frame must not print one."""
    keys = keyring(project_manager="sk-pm-key")

    assert "sk-pm-key" not in repr(keys)
    assert "sk-default-virtual-key" not in repr(keys)
    assert "sk-pm-key" not in str(vars(keys))


@pytest.mark.parametrize("empty", ["", "   "])
def test_the_keyring_refuses_an_empty_key(empty: str) -> None:
    """Found live, 2026-09-11: an empty virtual key does not produce a clean 401
    — ``Authorization: Bearer `` is an ILLEGAL HTTP header value, so httpx/h11
    raises ``LocalProtocolError`` and the adapter classifies it as
    ``overloaded``, i.e. RETRYABLE. A misconfigured key would then be retried
    three times per turn and reported as an upstream outage.

    Fail closed at construction instead: an empty key is a configuration fault,
    and C2 §3's gateway lane requires a real one."""
    with pytest.raises(ValueError, match="empty"):
        VirtualKeyring(default=SecretStr(empty))

    with pytest.raises(ValueError, match="empty"):
        VirtualKeyring(
            default=SecretStr("sk-default"), per_agent={"project_manager": SecretStr(empty)}
        )


def test_the_provider_holds_no_plaintext_key_attribute() -> None:
    subject = GatewayProvider(
        base_url=BASE_URL, keys=keyring(project_manager="sk-pm-key"), catalogue=catalogue()
    )

    assert "sk-pm-key" not in repr(vars(subject))


# --------------------------------------------------------------------------- #
# cost is SUNIL's number (C2 §2)
# --------------------------------------------------------------------------- #
async def test_usage_cost_is_computed_from_models_yaml_not_from_the_gateway() -> None:
    """The gateway may report a cost; ours is the authoritative one, because it
    is the versioned one. 100 in / 25 out on ``claude-sonnet`` at $3/$15 per
    Mtok = 0.000675."""
    body = completion_body(tokens=(100, 25))
    body["usage"]["cost"] = 999.0  # a gateway-reported cost, deliberately absurd
    handler = responder(body)

    result = await provider(handler).complete(request())

    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 25
    assert result.usage.cost_usd == pytest.approx(0.000675)


async def test_provider_model_reports_what_actually_served_the_call() -> None:
    handler = responder(completion_body())

    result = await provider(handler).complete(request())

    assert result.provider_model == "claude-sonnet-4-5"  # the gateway's own report


# --------------------------------------------------------------------------- #
# error classification (C2 §4)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "status,body,kind,retryable",
    [
        (401, {"error": {"message": "Authentication Error, No api key passed in."}}, "auth", False),
        (403, {"error": {"message": "forbidden"}}, "auth", False),
        (429, {"error": {"message": "rate limit"}}, "rate_limit", True),
        (500, {"error": {"message": "boom"}}, "overloaded", True),
        (529, {"error": {"message": "overloaded"}}, "overloaded", True),
        (400, {"error": {"message": "invalid schema"}}, "bad_request", False),
        (404, {"error": {"message": "no such model"}}, "bad_request", False),
        (
            400,
            {"error": {"message": "Budget has been exceeded! Current cost: 1.0"}},
            "budget_exceeded",
            False,
        ),
        (
            429,
            {"error": {"message": "ExceededBudget: Crossed spend within budget"}},
            "budget_exceeded",
            False,
        ),
    ],
    ids=[
        "401-auth",
        "403-auth",
        "429-rate-limit",
        "500-overloaded",
        "529-overloaded",
        "400-bad-request",
        "404-bad-request",
        "400-budget",
        "429-budget",
    ],
)
async def test_http_status_maps_to_the_contract_error_kind(
    status: int, body: dict, kind: str, retryable: bool
) -> None:
    handler = responder(body, status=status)

    with pytest.raises(ProviderError) as err:
        await provider(handler).complete(request())

    assert err.value.kind == kind
    assert err.value.retryable is retryable


async def test_an_auth_failure_message_is_redacted() -> None:
    """The pinned LiteLLM echoes the presented key and its hash in the 401 body
    (observed live, 2026-09-11). Copying that body into an exception message
    would put a credential fragment into every log and traceback, so an ``auth``
    error carries the status and nothing else."""
    handler = responder(
        {
            "error": {
                "message": (
                    "Authentication Error, Invalid proxy server token passed. "
                    "Received API Key = sk-abc...xyz, Key Hash (Token) = "
                    "ad736e5d12eb7f490613c955681618c8400bf3cc"
                )
            }
        },
        status=401,
    )

    with pytest.raises(ProviderError) as err:
        await provider(handler).complete(request())

    message = str(err.value)
    assert "sk-abc" not in message
    assert "ad736e5d" not in message
    assert "401" in message


@pytest.mark.parametrize(
    "exception,kind",
    [
        (httpx.ConnectTimeout("timed out"), "timeout"),
        (httpx.ReadTimeout("timed out"), "timeout"),
        (httpx.ConnectError("refused"), "overloaded"),
    ],
    ids=["connect-timeout", "read-timeout", "connect-error"],
)
async def test_transport_failures_map_to_retryable_kinds(exception, kind: str) -> None:
    def handler(sent: httpx.Request) -> httpx.Response:
        raise exception

    with pytest.raises(ProviderError) as err:
        await provider(handler).complete(request())

    assert err.value.kind == kind
    assert err.value.retryable is True
    assert err.value.usage is None  # nothing was served, nothing was burnt


# --------------------------------------------------------------------------- #
# structured output (C2 §4) — the adapter validates and RAISES, never re-asks
# --------------------------------------------------------------------------- #
async def test_unparseable_structured_output_raises_invalid_output_with_usage() -> None:
    """C2 §4 — ``invalid_output`` carries the tokens the failed attempt burned
    (M1 A-2), so the re-ask's cost is never invisible. And the adapter does NOT
    re-ask: it raises once, and the SUNIL policy owns the re-ask."""
    handler = responder(completion_body(content="Sure! Here is your plan: ```json {…"))

    with pytest.raises(ProviderError) as err:
        await provider(handler).complete(request(json_schema=PLAN_SCHEMA))

    assert err.value.kind == "invalid_output"
    assert err.value.retryable is True
    assert err.value.usage is not None
    assert err.value.usage.input_tokens == 100
    assert err.value.usage.cost_usd == pytest.approx(0.000675)
    assert len(handler.seen) == 1  # exactly one call: no adapter-side re-ask


async def test_structured_output_that_parses_to_a_non_object_is_invalid_output() -> None:
    handler = responder(completion_body(content="[1, 2, 3]"))

    with pytest.raises(ProviderError) as err:
        await provider(handler).complete(request(json_schema=PLAN_SCHEMA))

    assert err.value.kind == "invalid_output"


async def test_structured_output_is_never_repaired_by_stripping_fences() -> None:
    """M1 §6.1, ported: no regex rescue, no fence stripping, no "retry with a
    nudge" inside the adapter. Layer 2 of the plan-validation chain returns
    ``parsed`` only on a clean parse."""
    fenced = '```json\n{"intent": "x", "steps": []}\n```'
    handler = responder(completion_body(content=fenced))

    with pytest.raises(ProviderError) as err:
        await provider(handler).complete(request(json_schema=PLAN_SCHEMA))

    assert err.value.kind == "invalid_output"


async def test_a_completion_with_no_content_is_invalid_output_under_a_schema() -> None:
    body = completion_body()
    body["choices"][0]["message"] = {"role": "assistant"}
    handler = responder(body)

    with pytest.raises(ProviderError) as err:
        await provider(handler).complete(request(json_schema=PLAN_SCHEMA))

    assert err.value.kind == "invalid_output"


async def test_a_tool_call_in_the_response_is_refused_loudly() -> None:
    """We never send ``tools``, so a response carrying ``tool_calls`` means the
    gateway or the model invented a channel this seam does not have. Fail
    closed: a silently ignored tool call is how a second path to a privileged
    action starts."""
    body = completion_body(content="", finish="tool_calls")
    body["choices"][0]["message"]["tool_calls"] = [
        {"id": "call_1", "function": {"name": "rm", "arguments": "{}"}}
    ]
    handler = responder(body)

    with pytest.raises(ProviderError) as err:
        await provider(handler).complete(request())

    assert err.value.kind == "bad_request"
    assert "tool" in str(err.value).lower()


@pytest.mark.parametrize(
    "wire,expected",
    [("stop", "stop"), ("length", "max_tokens"), ("content_filter", "refusal")],
)
async def test_finish_reason_is_mapped_to_the_contracts_vocabulary(
    wire: str, expected: str
) -> None:
    handler = responder(completion_body(finish=wire))

    result = await provider(handler).complete(request())

    assert result.finish_reason == expected


# --------------------------------------------------------------------------- #
# startup model parity check (C2 §3)
# --------------------------------------------------------------------------- #
def models_responder(ids: list[str], status: int = 200):
    seen: list[httpx.Request] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        seen.append(sent)
        return httpx.Response(
            status,
            json={"object": "list", "data": [{"id": model_id} for model_id in ids]},
        )

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


async def test_start_accepts_a_gateway_serving_every_catalogue_id() -> None:
    """The live shape: ``GET /v1/models`` → ``{"data": [{"id": "claude-sonnet"},
    …]}`` (verified against the pinned LiteLLM v1.83.14 on 2026-09-11)."""
    handler = models_responder(list(GATEWAY_MODEL_ALIASES))

    await provider(handler).start()

    assert str(handler.seen[0].url) == f"{BASE_URL}/v1/models"
    assert handler.seen[0].method == "GET"
    assert handler.seen[0].headers["authorization"] == "Bearer sk-default-virtual-key"


async def test_start_refuses_to_boot_when_an_alias_is_missing() -> None:
    """C2 §3 — a drifted alias namespace is a BOOT failure, never a runtime
    400, and the error names the offenders."""
    handler = models_responder(["claude-sonnet", "claude-opus"])

    with pytest.raises(GatewayModelParityError) as err:
        await provider(handler).start()

    message = str(err.value)
    assert "claude-haiku" in message and "gpt-flagship" in message and "gpt-mini" in message
    assert "claude-sonnet" not in message.split("missing")[-1]


async def test_start_tolerates_a_gateway_serving_extra_models() -> None:
    """Asymmetric on purpose: every catalogue id MUST be served (C2 §3 says
    "refuses to boot ... if any config/models.yaml id is absent"), while an
    extra deployment on the proxy is the operator's business and cannot break a
    SUNIL request, because SUNIL only ever names its own ids."""
    handler = models_responder([*GATEWAY_MODEL_ALIASES, "some-experiment"])

    await provider(handler).start()


async def test_start_maps_an_unreachable_gateway_to_a_provider_error() -> None:
    def handler(sent: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ProviderError) as err:
        await provider(handler).start()

    assert err.value.kind in {"overloaded", "timeout"}


async def test_start_maps_a_401_to_auth_without_echoing_the_key() -> None:
    handler = models_responder([], status=401)

    with pytest.raises(ProviderError) as err:
        await provider(handler).start()

    assert err.value.kind == "auth"


# --------------------------------------------------------------------------- #
# streaming (ADR-027/028)
# --------------------------------------------------------------------------- #
def sse(chunks: list[str], *, usage: dict | None = None, finish: str = "stop") -> str:
    lines = []
    for chunk in chunks:
        lines.append(
            "data: "
            + json.dumps(
                {
                    "id": "chatcmpl-x",
                    "model": "claude-sonnet-4-5",
                    "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
                }
            )
        )
    lines.append(
        "data: "
        + json.dumps(
            {
                "id": "chatcmpl-x",
                "model": "claude-sonnet-4-5",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                "usage": usage or {"prompt_tokens": 100, "completion_tokens": 25},
            }
        )
    )
    lines.append("data: [DONE]")
    return "\n\n".join(lines) + "\n\n"


def stream_responder(text_chunks: list[str]):
    seen: list[httpx.Request] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        seen.append(sent)
        return httpx.Response(
            200,
            text=sse(text_chunks),
            headers={"content-type": "text/event-stream"},
        )

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


async def test_stream_tokens_partition_the_final_text_byte_for_byte() -> None:
    """C2 §2 — the ``done`` event is authoritative and the tokens are a
    projection of it: concatenating every token reproduces ``result.text``
    byte-for-byte, whitespace included (ADR-027's partition property)."""
    handler = stream_responder(["  keep  ", "the\n", "whitespace   ", "exactly "])

    events = [event async for event in provider(handler).stream(request())]

    body = json.loads(handler.seen[0].content)
    assert body["stream"] is True
    assert body["stream_options"] == {"include_usage": True}
    tokens = [event.token for event in events if event.type == "token"]
    done = [event for event in events if event.type == "done"]
    assert len(done) == 1
    assert events[-1] is done[0]
    assert "".join(tokens) == done[0].result.text
    assert done[0].result.text == "  keep  the\nwhitespace   exactly "
    assert done[0].result.usage.input_tokens == 100
    assert done[0].result.finish_reason == "stop"


async def test_stream_validates_structured_output_at_the_done_event() -> None:
    handler = stream_responder(['{"intent":', ' "x", "steps": []}'])

    events = [
        event async for event in provider(handler).stream(request(json_schema=PLAN_SCHEMA))
    ]

    assert events[-1].result.parsed == {"intent": "x", "steps": []}


async def test_a_stream_whose_text_is_not_valid_json_raises_invalid_output() -> None:
    """The ``done`` event never carries an unparsed plan: C2 §4's rule that
    ``parsed`` is non-None whenever a schema was set holds on the streaming leg
    too, and the failure arrives as ``invalid_output`` with the burnt usage."""
    handler = stream_responder(["not json at all"])

    with pytest.raises(ProviderError) as err:
        async for _ in provider(handler).stream(request(json_schema=PLAN_SCHEMA)):
            pass

    assert err.value.kind == "invalid_output"
    assert err.value.usage is not None and err.value.usage.output_tokens == 25


async def test_a_stream_error_status_raises_before_the_first_event() -> None:
    def handler(sent: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "slow down"}})

    seen = []
    with pytest.raises(ProviderError) as err:
        async for event in provider(handler).stream(request()):
            seen.append(event)

    assert err.value.kind == "rate_limit"
    assert seen == []
