"""Shared fixtures for `sunil.providers` unit tests.

Builds real `anthropic` exception instances (so the adapter's `except`
clauses are exercised against the actual vendor types, not a stand-in) and
a fake `messages.create` client double — no network, no key
(`docs/M1_BUILD_PLAN.md` T6).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import anthropic
import httpx


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
    """Not on `ARCHITECTURE_V1.md` §4.3's verified transient/permanent
    lists — used to prove the adapter's conservative catch-all (unlisted
    `AnthropicError` -> permanent, never silently retried on an
    assumption the architecture doc never made)."""
    return anthropic.OverloadedError("overloaded", response=make_httpx_response(529), body=None)


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
