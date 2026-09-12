"""Scripted ``LLMProvider`` doubles for the retry/router unit tests.

Deliberately NOT a mock library: each double is a real object implementing C2
§2's protocol, so every assertion in these tests is about SUNIL's own behaviour
(how many times it called, with what) rather than about a mock's recorded
expectations.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence

from sunil.providers.base import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    LLMProvider,
    ProviderError,
    StreamEvent,
    Usage,
)

USAGE = Usage(input_tokens=100, output_tokens=25, cost_usd=0.000125)


def ok(text: str = "ok") -> CompletionResult:
    return CompletionResult(
        text=text,
        parsed=None,
        usage=USAGE.model_copy(deep=True),
        provider_model="double-1",
        finish_reason="stop",
    )


class ScriptedProvider:
    """Returns/raises the next scripted outcome per call; the LAST outcome
    repeats forever, so "raises on every call" needs one entry."""

    def __init__(self, outcomes: Sequence[CompletionResult | ProviderError]) -> None:
        assert outcomes, "a scripted provider needs at least one outcome"
        self.name = "scripted"
        self.calls: list[CompletionRequest] = []
        self._outcomes = list(outcomes)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        self.calls.append(request)
        index = min(len(self.calls) - 1, len(self._outcomes) - 1)
        outcome = self._outcomes[index]
        if isinstance(outcome, ProviderError):
            raise outcome
        return outcome

    def stream(self, request: CompletionRequest) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError("the retry/router unit tests exercise complete() only")


def always(kind: str, *, retryable: bool = True, usage: Usage | None = USAGE) -> ScriptedProvider:
    return ScriptedProvider(
        [
            ProviderError(
                kind=kind,  # type: ignore[arg-type]
                retryable=retryable,
                usage=None if usage is None else usage.model_copy(deep=True),
                provider_model="double-1",
            )
        ]
    )


def failing_then_ok(kind: str, *, failures: int = 1) -> ScriptedProvider:
    errors: list[CompletionResult | ProviderError] = [
        ProviderError(
            kind=kind,  # type: ignore[arg-type]
            retryable=True,
            usage=USAGE.model_copy(deep=True),
            provider_model="double-1",
        )
        for _ in range(failures)
    ]
    return ScriptedProvider([*errors, ok()])


def request(
    message: str = "hello",
    *,
    model: str = "claude-sonnet",
    json_schema: dict | None = None,
    max_tokens: int = 512,
    privacy_class: str = "internal",
) -> CompletionRequest:
    return CompletionRequest(
        model=model,
        messages=[ChatMessage(role="user", content=message)],
        max_tokens=max_tokens,
        json_schema=json_schema,
        agent_id="project_manager",
        request_id="req-1",
        privacy_class=privacy_class,  # type: ignore[arg-type]
    )


class RecordingSleep:
    """Replaces ``asyncio.sleep`` so backoff is asserted, not waited for."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


#: Static conformance witnesses — the doubles satisfy C2 §2 structurally.
_check: LLMProvider = ScriptedProvider([ok()])
