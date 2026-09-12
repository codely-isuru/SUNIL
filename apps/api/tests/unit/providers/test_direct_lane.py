"""The DIRECT lane — the documented fallback of C2 §3's kill switch.

``providers/anthropic.py`` and ``providers/openai.py`` speak to the vendors with
``httpx`` (no SDK), reading each model's ``provider_model_id`` from
``config/models.yaml`` — the router namespace is lane-invariant, so the SAME
alias ``claude-sonnet`` reaches the vendor as its native id here and as the
alias itself through the gateway.
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from sunil.core.routing.catalogue import ModelCatalogue
from sunil.providers.anthropic import AnthropicProvider
from sunil.providers.base import (
    ChatMessage,
    CompletionRequest,
    LLMProvider,
    PrivacyClass,
    ProviderError,
)
from sunil.providers.openai import OpenAIProvider
from tests.unit.routing.test_catalogue import repo_root

PLAN_SCHEMA = {"type": "object", "required": ["intent", "steps"]}


def catalogue() -> ModelCatalogue:
    return ModelCatalogue.load(repo_root() / "config" / "models.yaml")


def request(message: str = "hello", *, model: str, json_schema: dict | None = None):
    return CompletionRequest(
        model=model,
        messages=[
            ChatMessage(role="system", content="be brief"),
            ChatMessage(role="user", content=message),
        ],
        max_tokens=512,
        json_schema=json_schema,
        agent_id="project_manager",
        request_id="req-42",
        privacy_class=PrivacyClass.INTERNAL,
    )


def responder(body: dict, status: int = 200):
    seen: list[httpx.Request] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        seen.append(sent)
        return httpx.Response(status, json=body)

    handler.seen = seen  # type: ignore[attr-defined]
    return handler


def anthropic(handler, base_url: str = "http://localhost:9101") -> AnthropicProvider:
    return AnthropicProvider(
        api_key=SecretStr("sk-ant-test"),
        base_url=base_url,
        catalogue=catalogue(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def openai(handler, base_url: str = "http://localhost:9102") -> OpenAIProvider:
    return OpenAIProvider(
        api_key=SecretStr("sk-oai-test"),
        base_url=base_url,
        catalogue=catalogue(),
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


ANTHROPIC_BODY = {
    "id": "msg_1",
    "model": "claude-sonnet-4-5",
    "stop_reason": "end_turn",
    "content": [{"type": "text", "text": "hi there"}],
    "usage": {"input_tokens": 100, "output_tokens": 25},
}

OPENAI_BODY = {
    "id": "chatcmpl-1",
    "model": "gpt-5",
    "choices": [
        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi there"}}
    ],
    "usage": {"prompt_tokens": 100, "completion_tokens": 25},
}


_checks: list[LLMProvider] = [
    AnthropicProvider(
        api_key=SecretStr("k"), base_url="http://localhost:1", catalogue=catalogue()
    ),
    OpenAIProvider(api_key=SecretStr("k"), base_url="http://localhost:2", catalogue=catalogue()),
]


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #
async def test_anthropic_sends_the_provider_native_model_id_not_the_alias() -> None:
    handler = responder(ANTHROPIC_BODY)

    result = await anthropic(handler).complete(request(model="claude-sonnet"))

    sent = handler.seen[0]
    assert str(sent.url).endswith("/v1/messages")
    body = json.loads(sent.content)
    assert body["model"] == "claude-sonnet-4-5"  # provider_model_id from models.yaml
    assert result.provider_model == "claude-sonnet-4-5"
    assert result.text == "hi there"
    assert result.usage.cost_usd == pytest.approx(0.000675)


async def test_anthropic_hoists_system_messages_into_the_system_parameter() -> None:
    """The vendor API takes ``system`` as its own top-level field, not as a
    message role — sending it as a message silently changes the prompt."""
    handler = responder(ANTHROPIC_BODY)

    await anthropic(handler).complete(request(model="claude-sonnet"))

    body = json.loads(handler.seen[0].content)
    assert body["system"] == "be brief"
    assert [m["role"] for m in body["messages"]] == ["user"]


async def test_anthropic_sends_auth_and_version_headers_and_no_tools() -> None:
    handler = responder(ANTHROPIC_BODY)

    await anthropic(handler).complete(request(model="claude-sonnet"))

    sent = handler.seen[0]
    assert sent.headers["x-api-key"] == "sk-ant-test"
    assert sent.headers["anthropic-version"]
    assert "tools" not in json.loads(sent.content)


async def test_anthropic_structured_output_uses_output_config() -> None:
    body = dict(ANTHROPIC_BODY)
    body["content"] = [{"type": "text", "text": '{"intent": "x", "steps": []}'}]
    handler = responder(body)

    result = await anthropic(handler).complete(
        request(model="claude-sonnet", json_schema=PLAN_SCHEMA)
    )

    sent_body = json.loads(handler.seen[0].content)
    assert sent_body["output_config"]["format"] == {
        "type": "json_schema",
        "schema": PLAN_SCHEMA,
    }
    assert result.parsed == {"intent": "x", "steps": []}


@pytest.mark.parametrize(
    "stop_reason,expected",
    [
        ("end_turn", "stop"),
        ("stop_sequence", "stop"),
        ("max_tokens", "max_tokens"),
        ("refusal", "refusal"),
    ],
)
async def test_anthropic_stop_reason_mapping(stop_reason: str, expected: str) -> None:
    body = dict(ANTHROPIC_BODY, stop_reason=stop_reason)
    handler = responder(body)

    result = await anthropic(handler).complete(request(model="claude-sonnet"))

    assert result.finish_reason == expected


@pytest.mark.parametrize(
    "status,kind",
    [(401, "auth"), (429, "rate_limit"), (529, "overloaded"), (400, "bad_request")],
)
async def test_anthropic_status_mapping(status: int, kind: str) -> None:
    handler = responder({"error": {"message": "x"}}, status=status)

    with pytest.raises(ProviderError) as err:
        await anthropic(handler).complete(request(model="claude-sonnet"))

    assert err.value.kind == kind


async def test_anthropic_refuses_a_model_that_is_not_its_own() -> None:
    """A routing bug must not reach the wire as a vendor 404: the adapter checks
    the catalogue's ``provider`` for the alias it was handed."""
    handler = responder(ANTHROPIC_BODY)

    with pytest.raises(ProviderError) as err:
        await anthropic(handler).complete(request(model="gpt-mini"))

    assert err.value.kind == "bad_request"
    assert handler.seen == []


# --------------------------------------------------------------------------- #
# OpenAI
# --------------------------------------------------------------------------- #
async def test_openai_sends_the_provider_native_model_id() -> None:
    handler = responder(OPENAI_BODY)

    result = await openai(handler).complete(request(model="gpt-flagship"))

    sent = handler.seen[0]
    assert str(sent.url).endswith("/v1/chat/completions")
    assert sent.headers["authorization"] == "Bearer sk-oai-test"
    assert json.loads(sent.content)["model"] == "gpt-5"
    assert result.text == "hi there"
    # 100 in / 25 out on gpt-flagship at $1.25/$10 per Mtok.
    assert result.usage.cost_usd == pytest.approx(0.000375)


async def test_openai_keeps_system_messages_in_the_message_list() -> None:
    handler = responder(OPENAI_BODY)

    await openai(handler).complete(request(model="gpt-flagship"))

    body = json.loads(handler.seen[0].content)
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "tools" not in body


async def test_openai_carries_no_metadata_because_there_is_no_gateway_to_log_it() -> None:
    """``metadata`` is a LiteLLM/OpenAI-proxy convention for gateway logs
    (C2 §3). Sending correlation ids to the vendor in the direct lane would be
    an unnecessary disclosure, and the audit spine already has them."""
    handler = responder(OPENAI_BODY)

    await openai(handler).complete(request(model="gpt-flagship"))

    assert "metadata" not in json.loads(handler.seen[0].content)


async def test_openai_refuses_a_model_that_is_not_its_own() -> None:
    handler = responder(OPENAI_BODY)

    with pytest.raises(ProviderError) as err:
        await openai(handler).complete(request(model="claude-sonnet"))

    assert err.value.kind == "bad_request"
    assert handler.seen == []


async def test_openai_structured_output_and_invalid_output_carry_usage() -> None:
    body = json.loads(json.dumps(OPENAI_BODY))
    body["choices"][0]["message"]["content"] = "definitely not json"
    handler = responder(body)

    with pytest.raises(ProviderError) as err:
        await openai(handler).complete(request(model="gpt-flagship", json_schema=PLAN_SCHEMA))

    assert err.value.kind == "invalid_output"
    assert err.value.usage is not None and err.value.usage.input_tokens == 100
