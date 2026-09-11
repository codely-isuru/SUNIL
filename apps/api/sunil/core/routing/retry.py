"""The ONE retry layer in SUNIL (C2 §4 "Retry ownership").

The rules, all normative:

* **There is exactly one retry layer and it is this one.** The gateway runs
  ``num_retries: 0`` (C2 §3) because a gateway-side retry is invisible to the
  A-2 usage rule and burns unrecorded tokens; the SDK-free adapters retry
  nothing either. The adapter *detects and classifies*, and raises.
* **``invalid_output`` gets at most ONE re-ask.** The adapter owns the wire
  shape, so it attempts the parse and raises ``invalid_output``; this policy is
  the named re-asker. Two attempts, then the failure surfaces (on the PLAN stage
  the orchestrator turns that into ``plan_rejected`` — free-form output never
  becomes a plan).
* **``retryable=True`` marks ELIGIBILITY, not a budget.** The policy caps the
  count; a ``retryable=False`` from the adapter is still obeyed, because the
  adapter may know that *this* failure is hopeless.
* **Usage accumulates across attempts INCLUDING failures** (M1 A-2): the total
  on the outcome — and on a terminal ``ProviderError`` — is what the caller
  writes to ``llm_calls``, so a retry's cost is never invisible.
* **An attempt that cannot fit the remaining turn deadline is never started**
  (M1 §5.3): "a retry that cannot finish is not a retry, it is a way to blow the
  latency budget quietly".

Backoff bases are M1's (1 s / 2 s / 4 s, full jitter). An ``invalid_output``
re-ask does NOT sleep: nothing upstream is overloaded, and a 1-4 s pause inside
a 40 s turn deadline buys nothing.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from sunil.core.routing.pricing import sum_usage
from sunil.providers.base import CompletionRequest, CompletionResult, ProviderError, Usage

#: Attempts per logical request for an ordinary transient failure (M1's value).
MAX_ATTEMPTS = 3

#: Kind-specific caps. ``invalid_output``: C2 §4's ONE re-ask. ``timeout``:
#: C2 §4 says "retried once" — a read timeout usually means the request is
#: still being served upstream, so hammering it multiplies the spend.
MAX_ATTEMPTS_BY_KIND: dict[str, int] = {"invalid_output": 2, "timeout": 2}

#: The kinds C2 §4 marks retryable at all. ``auth``, ``bad_request`` and
#: ``budget_exceeded`` are terminal by contract and must never be re-sent.
RETRYABLE_KINDS = frozenset({"rate_limit", "overloaded", "timeout", "invalid_output"})

#: Kinds that are re-asked immediately rather than after a backoff.
_NO_BACKOFF_KINDS = frozenset({"invalid_output"})

_BACKOFF_BASE_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)


class TurnDeadlineExceeded(Exception):
    """The remaining turn budget cannot accommodate another attempt.

    Deliberately **not** a ``ProviderError``: the provider was never called, so
    there is no attempt to record and no usage to account for.
    """

    def __init__(self, *, remaining_s: float, needed_s: float) -> None:
        self.remaining_s = remaining_s
        self.needed_s = needed_s
        super().__init__(
            f"turn deadline: only {remaining_s:.1f}s remaining, this attempt "
            f"needs up to {needed_s:.1f}s"
        )


def backoff_seconds(
    failed_attempts: int, *, rand: Callable[[], float] = random.random
) -> float:
    """Full jitter: ``sleep = random() * base``, bases 1 s / 2 s / 4 s.

    ``failed_attempts`` is how many attempts have failed *so far*. ``rand`` is
    injectable so a test asserts the exact base instead of depending on a draw.
    """
    index = min(max(failed_attempts - 1, 0), len(_BACKOFF_BASE_SECONDS) - 1)
    return rand() * _BACKOFF_BASE_SECONDS[index]


class _Provider(Protocol):
    """The slice of C2 §2's ``LLMProvider`` this policy uses."""

    name: str

    async def complete(self, request: CompletionRequest) -> CompletionResult: ...


@dataclass(frozen=True)
class AttemptRecord:
    """One provider attempt — produced per ATTEMPT, never per logical request
    (M1 A-2), including failures, so the caller can write one ``llm_calls`` row
    each."""

    attempt: int
    provider: str
    usage: Usage | None
    error_kind: str | None
    provider_model: str | None


@dataclass(frozen=True)
class RetryOutcome:
    result: CompletionResult
    attempts: tuple[AttemptRecord, ...]
    usage: Usage  # the A-2 total across every attempt, failures included


class RetryPolicy:
    """C2 §4's policy. Stateless per call; safe to share across turns."""

    def __init__(
        self,
        *,
        max_attempts: int = MAX_ATTEMPTS,
        max_attempts_by_kind: dict[str, int] | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        rand: Callable[[], float] = random.random,
        remaining_deadline_s: Callable[[], float] | None = None,
    ) -> None:
        self._max_attempts = max_attempts
        self._max_attempts_by_kind = dict(
            max_attempts_by_kind if max_attempts_by_kind is not None else MAX_ATTEMPTS_BY_KIND
        )
        self._sleep = sleep
        self._rand = rand
        # The turn-deadline seam (M1 §5.3). Absent by default rather than
        # defaulted to an invented budget: the orchestrator owns the clock and
        # injects its own remaining-time callable when it has one.
        self._remaining_deadline_s = remaining_deadline_s

    def attempt_budget(self, kind: str) -> int:
        return min(self._max_attempts_by_kind.get(kind, self._max_attempts), self._max_attempts)

    async def execute(
        self,
        *,
        provider: _Provider,
        request: CompletionRequest,
        attempt_timeout_s: float | None = None,
    ) -> RetryOutcome:
        """Run one **logical** request to a result, or raise.

        Raises ``TurnDeadlineExceeded`` if the next attempt cannot fit the
        remaining budget, and ``ProviderError`` when the attempts for that kind
        are exhausted — with ``retryable=False`` (it is terminal now) and
        ``usage`` set to the accumulated total, the original chained as
        ``__cause__``. Non-provider exceptions (e.g. the fake's
        ``AssertionError``) propagate unretried: a programming error run three
        times is still a programming error.
        """
        attempts: list[AttemptRecord] = []
        attempt = 0
        while True:
            attempt += 1
            self._check_deadline(attempt_timeout_s)
            try:
                result = await provider.complete(request)
            except ProviderError as error:
                attempts.append(
                    AttemptRecord(
                        attempt=attempt,
                        provider=provider.name,
                        usage=error.usage,
                        error_kind=error.kind,
                        provider_model=error.provider_model,
                    )
                )
                if not self._may_retry(error, attempt):
                    terminal = self._terminal(error, attempts)
                    if terminal is error:
                        raise  # the adapter's own object, traceback intact
                    raise terminal from error
                if error.kind not in _NO_BACKOFF_KINDS:
                    await self._sleep(backoff_seconds(attempt, rand=self._rand))
                continue

            attempts.append(
                AttemptRecord(
                    attempt=attempt,
                    provider=provider.name,
                    usage=result.usage,
                    error_kind=None,
                    provider_model=result.provider_model,
                )
            )
            return RetryOutcome(
                result=result,
                attempts=tuple(attempts),
                usage=sum_usage(record.usage for record in attempts),
            )

    # -- internals ---------------------------------------------------------- #
    def _check_deadline(self, attempt_timeout_s: float | None) -> None:
        if self._remaining_deadline_s is None or attempt_timeout_s is None:
            return
        remaining = self._remaining_deadline_s()
        if remaining < attempt_timeout_s:
            raise TurnDeadlineExceeded(remaining_s=remaining, needed_s=attempt_timeout_s)

    def _may_retry(self, error: ProviderError, attempts_made: int) -> bool:
        if error.kind not in RETRYABLE_KINDS:
            return False
        if not error.retryable:
            # The flag marks eligibility (C2 §4) — an adapter that says "not
            # this one" is obeyed, even for an ordinarily retryable kind.
            return False
        return attempts_made < self.attempt_budget(error.kind)

    def _terminal(
        self, error: ProviderError, attempts: Sequence[AttemptRecord]
    ) -> ProviderError:
        """The exception the caller sees when the budget is spent.

        A single-attempt failure is re-raised AS IS (nothing was accumulated, so
        rewriting it would only lose the adapter's own object and traceback). A
        multi-attempt failure is re-raised as the same ``kind`` with the A-2
        total attached and ``retryable=False``, because the thing a caller must
        not do with an exhausted request is retry it again.
        """
        if len(attempts) <= 1:
            return error
        return ProviderError(
            kind=error.kind,
            retryable=False,
            provider_model=error.provider_model,
            usage=sum_usage(record.usage for record in attempts),
            message=(
                f"{error.kind} after {len(attempts)} attempt(s) "
                f"(SUNIL retry policy exhausted): {error}"
            ),
        )
