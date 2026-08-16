"""FakeProvider — a deterministic, fault-injectable double for `sunil.providers.base.LLMProvider`.

This is the piece of shared infrastructure docs/M1_BUILD_PLAN.md's T18 entry names
explicitly: "a FakeProvider implementing LLMProvider for deterministic and
fault-injected runs (malformed plan for ET-7; transient-then-success for ET-8; a
transient-forever mode for the turn-deadline path)".

It deliberately imports NOTHING from `sunil` at module scope. `LLMProvider` (see
ARCHITECTURE_V1.md §4.2) is a `typing.Protocol`, which is structural, not nominal —
Python does not require a class to inherit a Protocol to satisfy it, so this class is
importable and constructible today, before `sunil.providers.base` exists, and will
still satisfy the real Protocol once it does, with zero changes.

QA's own exit tests do NOT primarily drive their fault injection through this class —
see docs/M1_BUILD_PLAN.md T18 ambiguity notes in the T18 report: there is no documented
seam for handing a Python object to the real Model Router's constructor, so QA drives
its own tests through the verified `ANTHROPIC_BASE_URL` HTTP seam in
`_mock_upstreams.py` instead. This class exists so that whichever constructor T6 ends
up building (e.g. `ModelRouter(providers={"anthropic": fake_provider})`, matching
ARCHITECTURE_V1.md §4.6's own words "a test that constructs the router with a fake
provider") has a ready-made, spec-shaped double to use — including from T6's/T9's/
T10's own `tests/unit/` suites, which QA does not own.

`request.json_schema` is the one **documented** field (ARCHITECTURE_V1.md §4.2) that
distinguishes an M1 "plan" call (schema-constrained) from an "analysis" call (free
text: "None -> free text; set -> structured output demanded"). Purpose is therefore
inferred from that field, never guessed from an undocumented parameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Any


@dataclass
class Scripted:
    """One scripted outcome for a single `generate()` call: either a response to
    return, or an exception instance to raise."""

    text: str | None = None
    input_tokens: int = 120
    output_tokens: int = 60
    stop_reason: str = "end_turn"
    raises: BaseException | None = None


class FakeProvider:
    """Duck-typed to `sunil.providers.base.LLMProvider`:

        name: str
        def capabilities(self, model: str) -> ModelCapabilities: ...
        async def generate(self, model: str, request: LLMRequest) -> LLMResponse: ...

    `generate()` returns a `SimpleNamespace` shaped exactly like the documented
    `LLMResponse` frozen dataclass (`text`, `data`, `provider`, `model`,
    `input_tokens`, `output_tokens`, `stop_reason`, `provider_request_id`,
    `latency_ms`) — callers that only read those documented fields (never
    `isinstance`-check the class) work identically against this fake and the real
    dataclass.
    """

    name = "fake"

    def __init__(self) -> None:
        self._schema_script: list[Scripted] = []
        self._freetext_script: list[Scripted] = []
        self.calls: list[dict[str, Any]] = []

    def script_structured(self, *outcomes: Scripted) -> None:
        """Outcomes for calls made WITH a json_schema (M1's "plan" purpose)."""
        self._schema_script.extend(outcomes)

    def script_freetext(self, *outcomes: Scripted) -> None:
        """Outcomes for calls made WITHOUT a json_schema (M1's "analysis" purpose)."""
        self._freetext_script.extend(outcomes)

    def capabilities(self, model: str) -> SimpleNamespace:
        return SimpleNamespace(
            context_window=1_000_000,
            max_output=128_000,
            supports_structured_output=True,
            input_usd_per_mtok=Decimal(2),
            output_usd_per_mtok=Decimal(10),
        )

    async def generate(self, model: str, request: Any) -> SimpleNamespace:
        has_schema = getattr(request, "json_schema", None) is not None
        queue = self._schema_script if has_schema else self._freetext_script
        self.calls.append(
            {
                "model": model,
                "has_schema": has_schema,
                "system": getattr(request, "system", None),
                "messages": getattr(request, "messages", None),
            }
        )
        if not queue:
            raise AssertionError(
                f"FakeProvider.generate() called (schema={has_schema}) with no scripted "
                f"outcome queued — this is a test-authoring bug, not a red-for-the-right-"
                f"reason result. Call script_structured()/script_freetext() first."
            )
        outcome = queue.pop(0) if len(queue) > 1 else queue[0]
        if outcome.raises is not None:
            raise outcome.raises
        return SimpleNamespace(
            text=outcome.text,
            data=None,
            provider="fake",
            model=model,
            input_tokens=outcome.input_tokens,
            output_tokens=outcome.output_tokens,
            stop_reason=outcome.stop_reason,
            provider_request_id="fake_" + str(len(self.calls)),
            latency_ms=1,
        )
