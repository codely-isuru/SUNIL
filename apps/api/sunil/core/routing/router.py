"""The Model Router (ADR-003, `ARCHITECTURE_V1.md` §4).

`ModelRouter.run()` is the **only** way anything in SUNIL calls an LLM.
Callers name a **capability**, never a vendor or a model (§33 rule 1) —
`sunil/providers/` is the only package permitted to import a vendor SDK
(FR-040's own acceptance criterion; checked by T19's import-boundary test,
run on every merge by T21).

**Trace stages are the caller's job, not this router's.** `model_selected`
(stage 4) and `llm_io` (stage 5) belong to the *first* logical request in
a turn — the orchestrator's own plan-generation call — while the PM
agent's analysis call is folded into stage 11 (`agent_result`) instead
(`ARCHITECTURE_V1.md` §3.4's table ties stage 5 to `purpose=plan`
specifically). Because `run()` is invoked once per **logical request**
and a turn makes at least two of those (plan, then analysis), it cannot
safely call `ctx.emit()` itself without risking a second `model_selected`/
`llm_io` emission on the analysis call — a `DuplicateStageEmission`
(§3.4: "at most once per turn"). So this router only *reads* the trace
context (`remaining_deadline_s()`, for the §5.3 deadline check); whoever
calls `run()` (T9 for the plan, T10/T11b for the analysis) emits the
stage that surrounds that particular call.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from sunil.core.registry.model_catalogue import ModelRegistry
from sunil.core.routing.capabilities import resolve_capability
from sunil.core.routing.pricing import compute_cost_micro_usd
from sunil.core.routing.retry import MAX_ATTEMPTS, TurnDeadlineExceeded, backoff_seconds
from sunil.core.trace.context import TraceContext
from sunil.providers.base import (
    ChatTurn,
    LLMPurpose,
    LLMRequest,
    LLMResponse,
    ProviderPermanentError,
    ProviderTransientError,
    StructuredOutputError,
)
from sunil.providers.registry import ProviderRegistry


class PrivacyLevel(StrEnum):
    """§4.5 / NFR-010: accepted and recorded, **not used for selection in
    M1** — the seam for V2's LOCAL-ONLY enforcement to be additive."""

    INTERNAL = "internal"


class CostPriority(StrEnum):
    """§4.5 / NFR-010: same story as `PrivacyLevel`."""

    BALANCED = "balanced"


class ErrorKind(StrEnum):
    """Shared vocabulary for `llm_calls.error_kind` and the trace
    `detail`/`tasks.failure_kind` the orchestrator (T11b) writes — a plain
    string, not a DB enum (`ARCHITECTURE_V1.md` §7.2: no native `ENUM`
    types), so the router and the orchestrator agree on spelling without
    either importing the other's module."""

    TRANSIENT_PROVIDER_ERROR = "transient_provider_error"
    PERMANENT_PROVIDER_ERROR = "permanent_provider_error"
    STRUCTURED_OUTPUT_ERROR = "structured_output_error"
    TURN_DEADLINE_EXCEEDED = "turn_deadline_exceeded"
    RETRIES_EXHAUSTED = "retries_exhausted"


class ProviderExhaustedError(Exception):
    """All `MAX_ATTEMPTS` provider attempts for one logical request failed.

    The orchestrator (T11b) turns this into the `provider_error` outcome
    (§11.3, ET-8). Deliberately not a `ProviderError` itself — it is the
    retry loop's *terminal* outcome, not a provider-boundary failure — but
    the last underlying error is chained via `__cause__` so nothing is
    lost.
    """


@dataclass(frozen=True)
class ProviderAttemptRecord:
    """Everything one `llm_calls` row needs (`ARCHITECTURE_V1.md` §7.3),
    minus the columns the writer assigns (`id`, `created_at`). Produced
    **once per provider attempt**, never per logical request (A-2) —
    including failed attempts, so a retry's cost is never invisible
    (§13.1).

    T6 has no dependency on T2's ORM (`docs/M1_BUILD_PLAN.md` §1.1's
    dependency table lists T3 + T1's trace interface only) — persisting
    this as an actual `llm_calls` row is the caller's business, via the
    injected `LLMCallRecorder` below. Field names match
    `sunil.db.models.LLMCall` one for one by design, so that wiring is a
    straight assignment, not a translation.
    """

    request_id: str
    task_id: str | None
    agent_id: str | None
    purpose: LLMPurpose
    capability: str
    provider: str
    model: str
    attempt: int
    request_system: str
    request_messages: list[ChatTurn]
    request_schema: dict[str, Any] | None
    response_text: str | None
    response_json: dict[str, Any] | None
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cost_micro_usd: int
    pricing_version: str
    latency_ms: int
    error_kind: str | None
    provider_request_id: str | None


class LLMCallRecorder:
    """Mirrors `TraceContext`/`NullTraceContext` (T1) deliberately: the
    same seam that let T6 be written and unit-tested against a fake trace
    context before T4's emitter existed lets whoever wires the real
    `llm_calls` writer (once a DB session is in scope — most naturally
    T11b, which already persists the turn) do so without a change to this
    router. Subclass and override `record()`.
    """

    async def record(self, attempt: ProviderAttemptRecord) -> None:  # pragma: no cover
        raise NotImplementedError


class NullLLMCallRecorder(LLMCallRecorder):
    """Records nothing but remembers every attempt in memory — the
    default, and what every unit test in this package uses."""

    def __init__(self) -> None:
        self.recorded: list[ProviderAttemptRecord] = []

    async def record(self, attempt: ProviderAttemptRecord) -> None:
        self.recorded.append(attempt)


class ModelRouter:
    """See module docstring. `run()` is the only way to call an LLM."""

    def __init__(
        self,
        *,
        model_registry: ModelRegistry,
        provider_registry: ProviderRegistry,
        recorder: LLMCallRecorder | None = None,
    ) -> None:
        self._model_registry = model_registry
        self._provider_registry = provider_registry
        self._recorder = recorder or NullLLMCallRecorder()

    async def run(
        self,
        *,
        capability: str,
        request: LLMRequest,
        purpose: LLMPurpose,
        ctx: TraceContext,
        request_id: str,
        task_id: str | None = None,
        agent_id: str | None = None,
        privacy_level: PrivacyLevel = PrivacyLevel.INTERNAL,
        cost_priority: CostPriority = CostPriority.BALANCED,
    ) -> LLMResponse:
        """One **logical** request — up to `MAX_ATTEMPTS` provider
        attempts, each individually recorded via the injected
        `LLMCallRecorder` (A-2).

        Raises `TurnDeadlineExceeded` if the very next attempt cannot fit
        the remaining `SUNIL_TURN_DEADLINE_S` budget, and
        `ProviderExhaustedError` if every attempt failed (permanently, or
        after `MAX_ATTEMPTS` transient failures).
        """
        del privacy_level, cost_priority  # accepted, not used for selection in M1 (NFR-010)

        resolved = resolve_capability(
            capability,
            model_registry=self._model_registry,
            provider_registry=self._provider_registry,
        )
        model_capabilities = resolved.provider.capabilities(resolved.model)
        pricing_version = self._model_registry.pricing_version

        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            remaining = ctx.remaining_deadline_s()
            if remaining < resolved.timeout_s:
                # An attempt whose own timeout exceeds what remains is not
                # started at all (§5.3) — nothing was attempted, so
                # nothing is recorded as an `llm_calls` row for it.
                raise TurnDeadlineExceeded(remaining_s=remaining, needed_s=resolved.timeout_s)

            if attempt > 1:
                await asyncio.sleep(backoff_seconds(attempt - 1))

            started = time.monotonic()
            try:
                response = await asyncio.wait_for(
                    resolved.provider.generate(
                        resolved.model, request, timeout_s=resolved.timeout_s
                    ),
                    timeout=resolved.timeout_s,
                )
            except TimeoutError as exc:
                last_error = exc
                await self._record_failed_attempt(
                    request_id=request_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    purpose=purpose,
                    capability=capability,
                    resolved_model=resolved.model,
                    provider_name=resolved.provider.name,
                    attempt=attempt,
                    request=request,
                    pricing_version=pricing_version,
                    started=started,
                    error_kind=ErrorKind.TRANSIENT_PROVIDER_ERROR,
                    input_tokens=0,
                    output_tokens=0,
                    provider_request_id=None,
                )
                continue
            except ProviderTransientError as exc:
                last_error = exc
                await self._record_failed_attempt(
                    request_id=request_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    purpose=purpose,
                    capability=capability,
                    resolved_model=resolved.model,
                    provider_name=resolved.provider.name,
                    attempt=attempt,
                    request=request,
                    pricing_version=pricing_version,
                    started=started,
                    error_kind=ErrorKind.TRANSIENT_PROVIDER_ERROR,
                    input_tokens=exc.input_tokens or 0,
                    output_tokens=exc.output_tokens or 0,
                    provider_request_id=exc.provider_request_id,
                )
                continue
            except StructuredOutputError as exc:
                last_error = exc
                await self._record_failed_attempt(
                    request_id=request_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    purpose=purpose,
                    capability=capability,
                    resolved_model=resolved.model,
                    provider_name=resolved.provider.name,
                    attempt=attempt,
                    request=request,
                    pricing_version=pricing_version,
                    started=started,
                    error_kind=ErrorKind.STRUCTURED_OUTPUT_ERROR,
                    input_tokens=exc.input_tokens or 0,
                    output_tokens=exc.output_tokens or 0,
                    provider_request_id=exc.provider_request_id,
                )
                raise ProviderExhaustedError(str(exc)) from exc
            except ProviderPermanentError as exc:
                last_error = exc
                await self._record_failed_attempt(
                    request_id=request_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    purpose=purpose,
                    capability=capability,
                    resolved_model=resolved.model,
                    provider_name=resolved.provider.name,
                    attempt=attempt,
                    request=request,
                    pricing_version=pricing_version,
                    started=started,
                    error_kind=ErrorKind.PERMANENT_PROVIDER_ERROR,
                    input_tokens=exc.input_tokens or 0,
                    output_tokens=exc.output_tokens or 0,
                    provider_request_id=exc.provider_request_id,
                )
                raise ProviderExhaustedError(str(exc)) from exc

            latency_ms = int((time.monotonic() - started) * 1000)
            cost_micro_usd = compute_cost_micro_usd(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                capabilities=model_capabilities,
            )
            await self._recorder.record(
                ProviderAttemptRecord(
                    request_id=request_id,
                    task_id=task_id,
                    agent_id=agent_id,
                    purpose=purpose,
                    capability=capability,
                    provider=resolved.provider.name,
                    model=resolved.model,
                    attempt=attempt,
                    request_system=request.system,
                    request_messages=request.messages,
                    request_schema=request.json_schema,
                    response_text=response.text,
                    response_json=response.data,
                    stop_reason=response.stop_reason,
                    input_tokens=response.input_tokens,
                    output_tokens=response.output_tokens,
                    cost_micro_usd=cost_micro_usd,
                    pricing_version=pricing_version,
                    latency_ms=latency_ms,
                    error_kind=None,
                    provider_request_id=response.provider_request_id,
                )
            )
            return response

        # MAX_ATTEMPTS transient failures, none of them permanent enough
        # to raise early.
        raise ProviderExhaustedError(
            f"{MAX_ATTEMPTS} provider attempts exhausted for capability {capability!r}"
        ) from last_error

    async def _record_failed_attempt(
        self,
        *,
        request_id: str,
        task_id: str | None,
        agent_id: str | None,
        purpose: LLMPurpose,
        capability: str,
        resolved_model: str,
        provider_name: str,
        attempt: int,
        request: LLMRequest,
        pricing_version: str,
        started: float,
        error_kind: ErrorKind,
        input_tokens: int,
        output_tokens: int,
        provider_request_id: str | None,
    ) -> None:
        """One `llm_calls` row for a failed attempt (A-2, §13.1) — cost is
        computed from whatever tokens the exception reported (zero for a
        connection failure/timeout that never got a response; real numbers
        for a structured-output failure that did)."""
        model_capabilities = self._provider_registry.get(provider_name).capabilities(resolved_model)
        latency_ms = int((time.monotonic() - started) * 1000)
        cost_micro_usd = compute_cost_micro_usd(
            input_tokens=input_tokens, output_tokens=output_tokens, capabilities=model_capabilities
        )
        await self._recorder.record(
            ProviderAttemptRecord(
                request_id=request_id,
                task_id=task_id,
                agent_id=agent_id,
                purpose=purpose,
                capability=capability,
                provider=provider_name,
                model=resolved_model,
                attempt=attempt,
                request_system=request.system,
                request_messages=request.messages,
                request_schema=request.json_schema,
                response_text=None,
                response_json=None,
                stop_reason=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_micro_usd=cost_micro_usd,
                pricing_version=pricing_version,
                latency_ms=latency_ms,
                error_kind=error_kind,
                provider_request_id=provider_request_id,
            )
        )
