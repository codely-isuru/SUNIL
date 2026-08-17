"""Shared fixtures for `sunil.providers` unit tests.

Builds real `anthropic`/`openai` exception instances (so each adapter's
`except` clauses are exercised against the actual vendor types, not a
stand-in) and fake `messages.create`/`chat.completions.create` client
doubles — no network, no key (`docs/M1_BUILD_PLAN.md` T6).

The `openai` fakes build on `httpx2`, not `httpx` — `openai==3.1.0`
depends on `httpx2` ("the next generation HTTP client", same author as
`httpx`), not the `httpx` used elsewhere in this codebase (T23, verified
against the installed package rather than assumed). `httpx2.Request`/
`Response` mirror `httpx`'s constructor shape exactly, confirmed here by
using them the same way the `anthropic` fakes above use `httpx`.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import httpx2
import openai


def make_httpx_request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def make_httpx_response(status_code: int) -> httpx.Response:
    return httpx.Response(status_code, request=make_httpx_request())


def make_connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=make_httpx_request())


def make_timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=make_httpx_request())


def make_rate_limit_error() -> anthropic.RateLimitError:
    return anthropic.RateLimitError("rate limited", response=make_httpx_response(429), body=None)


def make_internal_server_error() -> anthropic.InternalServerError:
    return anthropic.InternalServerError(
        "internal error", response=make_httpx_response(500), body=None
    )


def make_bad_request_error() -> anthropic.BadRequestError:
    return anthropic.BadRequestError("bad request", response=make_httpx_response(400), body=None)


def make_authentication_error() -> anthropic.AuthenticationError:
    return anthropic.AuthenticationError(
        "authentication failed", response=make_httpx_response(401), body=None
    )


def make_permission_denied_error() -> anthropic.PermissionDeniedError:
    return anthropic.PermissionDeniedError(
        "forbidden", response=make_httpx_response(403), body=None
    )


def make_not_found_error() -> anthropic.NotFoundError:
    return anthropic.NotFoundError("not found", response=make_httpx_response(404), body=None)


def make_unprocessable_entity_error() -> anthropic.UnprocessableEntityError:
    return anthropic.UnprocessableEntityError(
        "unprocessable", response=make_httpx_response(422), body=None
    )


def make_overloaded_error() -> anthropic.OverloadedError:
    """A-16: not on the old name-keyed transient list, but its
    `status_code` (529) is `>= 500` — proves classification is by status
    code, not by class name. A name-keyed list gets this one wrong."""
    return anthropic.OverloadedError("overloaded", response=make_httpx_response(529), body=None)


def make_conflict_error() -> anthropic.ConflictError:
    return anthropic.ConflictError("conflict", response=make_httpx_response(409), body=None)


def make_request_too_large_error() -> anthropic.RequestTooLargeError:
    return anthropic.RequestTooLargeError(
        "request too large", response=make_httpx_response(413), body=None
    )


def make_text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def make_anthropic_message(
    *,
    text: str,
    input_tokens: int = 10,
    output_tokens: int = 20,
    stop_reason: str = "end_turn",
    request_id: str | None = "req_fake_abc123",
) -> SimpleNamespace:
    """A minimal stand-in for `anthropic.types.Message` carrying exactly
    the attributes `AnthropicProvider.generate()` reads."""
    message = SimpleNamespace(
        content=[make_text_block(text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
        stop_reason=stop_reason,
    )
    message._request_id = request_id
    return message


class FakeMessagesResource:
    """Stands in for `anthropic.AsyncAnthropic().messages` — `outcomes` is
    consumed in order; an `Exception` instance is raised instead of
    returned."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeAnthropicClient:
    """Stands in for `anthropic.AsyncAnthropic` itself — only
    `.messages.create(...)` is ever called by `AnthropicProvider`."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.messages = FakeMessagesResource(outcomes)


# -- openai (T23) -------------------------------------------------------------


def make_openai_httpx_request() -> httpx2.Request:
    return httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")


def make_openai_httpx_response(status_code: int) -> httpx2.Response:
    return httpx2.Response(status_code, request=make_openai_httpx_request())


def make_openai_connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=make_openai_httpx_request())


def make_openai_timeout_error() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=make_openai_httpx_request())


def make_openai_rate_limit_error() -> openai.RateLimitError:
    return openai.RateLimitError(
        "rate limited", response=make_openai_httpx_response(429), body=None
    )


def make_openai_internal_server_error() -> openai.InternalServerError:
    return openai.InternalServerError(
        "internal error", response=make_openai_httpx_response(500), body=None
    )


def make_openai_bad_request_error() -> openai.BadRequestError:
    return openai.BadRequestError(
        "bad request", response=make_openai_httpx_response(400), body=None
    )


def make_openai_authentication_error() -> openai.AuthenticationError:
    return openai.AuthenticationError(
        "authentication failed", response=make_openai_httpx_response(401), body=None
    )


def make_openai_permission_denied_error() -> openai.PermissionDeniedError:
    return openai.PermissionDeniedError(
        "forbidden", response=make_openai_httpx_response(403), body=None
    )


def make_openai_not_found_error() -> openai.NotFoundError:
    return openai.NotFoundError("not found", response=make_openai_httpx_response(404), body=None)


def make_openai_conflict_error() -> openai.ConflictError:
    return openai.ConflictError("conflict", response=make_openai_httpx_response(409), body=None)


def make_openai_unprocessable_entity_error() -> openai.UnprocessableEntityError:
    return openai.UnprocessableEntityError(
        "unprocessable", response=make_openai_httpx_response(422), body=None
    )


def make_openai_unnamed_5xx_error() -> openai.APIStatusError:
    """A-16 applied to `openai`: `openai.APIStatusError` is directly
    constructible (not abstract) and carries no named subclass at 529 the
    way `anthropic.OverloadedError` does — an even stronger proof that
    classification is by `status_code` alone, not by class name, since
    this is not a named class at all."""
    return openai.APIStatusError(
        "mystery upstream error", response=make_openai_httpx_response(529), body=None
    )


def make_openai_message(
    *,
    content: str | None = "hi there",
    refusal: str | None = None,
    prompt_tokens: int = 10,
    completion_tokens: int = 20,
    finish_reason: str = "stop",
    request_id: str | None = "chatcmpl_fake_abc123",
) -> SimpleNamespace:
    """A minimal stand-in for `openai.types.chat.ChatCompletion` carrying
    exactly the attributes `OpenAIProvider.generate()` reads."""
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    usage = SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return SimpleNamespace(id=request_id, choices=[choice], usage=usage)


class FakeChatCompletionsResource:
    """Stands in for `openai.AsyncOpenAI().chat.completions` — only
    `.create(...)` is ever called by `OpenAIProvider`."""

    def __init__(self, outcomes: list[Any]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeChatResource:
    def __init__(self, outcomes: list[Any]) -> None:
        self.completions = FakeChatCompletionsResource(outcomes)


class FakeOpenAIClient:
    """Stands in for `openai.AsyncOpenAI` itself — only
    `.chat.completions.create(...)` is ever called by `OpenAIProvider`."""

    def __init__(self, outcomes: list[Any]) -> None:
        self.chat = FakeChatResource(outcomes)
