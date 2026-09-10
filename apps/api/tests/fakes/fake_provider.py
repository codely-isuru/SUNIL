"""``FakeProvider`` — C2 §5's fake specification, verbatim.

Source of truth: ``docs/contracts/C2-model-provider.md`` §5 (v1.0.0, FROZEN
2026-09-10). ``name="fake"``. Deterministic, no I/O, no sleep. Behaviour keys off
the **last user message** content.

Marker precedence follows the order of C2 §5's table (``PLAN:`` first, then
``FAIL:rate_limit``, ``FAIL:auth``, ``FAIL:invalid_output``, then the echo lane);
the contract does not define a message carrying two markers, so the table order
is the tie-break. Recorded as a finding in ``docs/tasks/P0-fakes.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from sunil.providers.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ProviderError,
    StreamEvent,
    Usage,
)

#: C2 §5's fixed plan JSON, exact value. Key order is the contract's.
FIXED_PLAN: dict = {
    "intent": "fake_intent",
    "confidence": 0.9,
    "privacy_level": "internal",
    "objective": "fake objective",
    "agents": ["project_manager"],
    "steps": [
        {
            "id": "step_1",
            "action": "tool_call",
            "tool": "fake_tool",
            "operation": "write_item",
            "params": {"key": "demo", "value": "1"},
        }
    ],
}

#: C2 §5 — usage on every successful call.
FIXED_USAGE = Usage(input_tokens=100, output_tokens=25, cost_usd=0.000125)

#: C2 §5 — the fake's exact partition rule, shared with C5 §4's streaming fake:
#: each maximal non-whitespace run captures its trailing whitespace; a leading
#: whitespace run is its own token.
PARTITION = re.compile(r"\S+\s*|\s+")


def partition(text: str) -> list[str]:
    """C2 §5's whitespace-preserving projection. ``"".join(partition(t)) == t``
    for ANY text — that byte-for-byte property is the contract, not an artefact."""
    return PARTITION.findall(text)


class FakeProvider:
    """C2 §5 fake. ``self.calls`` records every request (contract test 5's
    zero-call probe); ``FAIL:invalid_output`` uses an instance-level counter."""

    def __init__(self) -> None:
        self.name = "fake"
        self.calls: list[CompletionRequest] = []
        self.invalid_output_calls = 0

    # -- C2 §2 protocol ---------------------------------------------------- #
    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls.append(request)
        return self._result(request)

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        """C2 §2's signature is a plain ``def`` returning an async iterator.

        The result is computed eagerly so that ``FAIL:*`` markers raise before
        the first event, exactly as C2 §5 requires.
        """
        self.calls.append(request)
        result = self._result(request)
        return self._emit(result)

    # -- internals ---------------------------------------------------------- #
    async def _emit(self, result: CompletionResult) -> AsyncIterator[StreamEvent]:
        for token in partition(result.text):
            yield StreamEvent(type="token", token=token)
        yield StreamEvent(type="done", result=result)

    def _result(self, request: CompletionRequest) -> CompletionResult:
        message = self._last_user_message(request)

        if "PLAN:" in message:
            assert request.json_schema is not None, "plan requested without schema"
            return self._plan_result()

        if "FAIL:rate_limit" in message:
            raise ProviderError(kind="rate_limit", retryable=True)

        if "FAIL:auth" in message:
            raise ProviderError(kind="auth", retryable=False)

        if "FAIL:invalid_output" in message and request.json_schema is not None:
            self.invalid_output_calls += 1
            if self.invalid_output_calls == 1:
                raise ProviderError(
                    kind="invalid_output", retryable=True, usage=FIXED_USAGE
                )
            return self._plan_result()

        return CompletionResult(
            text=f"FAKE: {message}",
            parsed=None,
            usage=FIXED_USAGE,
            provider_model="fake-1",
            finish_reason="stop",
        )

    @staticmethod
    def _plan_result() -> CompletionResult:
        return CompletionResult(
            text=json.dumps(FIXED_PLAN, separators=(",", ":")),
            parsed=FIXED_PLAN,
            usage=FIXED_USAGE,
            provider_model="fake-1",
            finish_reason="stop",
        )

    @staticmethod
    def _last_user_message(request: CompletionRequest) -> str:
        user_messages: list[ChatMessage] = [
            m for m in request.messages if m.role == "user"
        ]
        assert user_messages, "fake provider called without a user message"
        return user_messages[-1].content


#: Static conformance witness (F2) — FakeProvider satisfies C2 §2's LLMProvider
#: structurally (note `stream` is a plain def returning an async iterator).
_check: LLMProvider = FakeProvider()
