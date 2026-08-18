# ADR-028 — Only the analysis call streams. The plan call is consumed whole.

**Status:** Proposed (Architect, M2) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Context refs:** ADR-004 (+ Amendment 1), ADR-015, ADR-003; `ARCHITECTURE_V1.md` §4.2, §6.1, §6.2;
`ARCHITECTURE_M2_STREAMING.md` §5; FR-024e, NFR-011/012; ET-7, ET-9.

## Context

M1 has two logical LLM stages (ADR-015): a **plan** call producing a structured JSON plan, and an
**analysis** call whose free text *is* the user-facing answer. M2 adds streaming. The question is which
of the two streams.

The naive answer is "both — more streaming is better", and it is wrong in a way that touches the most
important control in the system.

## Decision

**The analysis call streams. The plan call does not, and must not.**

### Why the plan call must not stream

ADR-004's whole argument is that **only a fully validated plan reaches an executor**. Five layers stand
between raw model output and a tool call: registry-derived enums enforced by constrained decoding, a
provider that refuses partial parses, Pydantic `extra="forbid"`, an independent registry re-check, and
a `ValidatedPlan` with a runtime `isinstance` guard at three privileged entry points.

Every one of those operates on a **whole document**:

* A partial JSON object cannot be parsed, so it cannot be validated.
* It cannot be re-checked against the registry, because the field naming the tool may not have arrived.
* It cannot become a `ValidatedPlan`, because the constructor demands a complete, conforming object.

**A plan that is 80 % arrived is not 80 % validated.** Streaming it would produce bytes that nobody may
act on, purely so that something is moving on the wire — and it would put partially-formed model output
in front of code whose entire contract is that it never sees any.

It also buys nothing a user can perceive. Plan tokens are `{"steps":[{"tool":"github"…` — not text a
person reads. The stage frames already tell them SUNIL is planning.

**The consequence, stated plainly because it is a user-visible one:** nothing is typed or spoken for
the first **~3.0–4.5 s** of a turn (derived, not measured — M2's T40 measures it). That window is
carried by `stage` frames, exactly as the four-phase `WorkIndicator` carries it today. It is the shape
of a two-LLM-stage pipeline, not a limitation of the transport, and no transport choice can shorten it.

### What the interface looks like

```python
@dataclass(frozen=True)
class StreamDelta:
    text: str                       # token delta; never None, may be ""

@dataclass(frozen=True)
class StreamResult:
    text: str                                  # the full accumulated answer
    input_tokens: int; output_tokens: int
    provider: str; model: str
    stop_reason: str | None
    provider_request_id: str | None
    latency_ms: int

class LLMProvider(Protocol):
    ...
    def generate_stream(self, model: str, request: LLMRequest) -> LLMStream: ...
```

`LLMStream` is an async iterator of `StreamDelta` **with a terminal `result() -> StreamResult`**, not a
bare `AsyncIterator[str]`. Token counts and `stop_reason` arrive *after* the last delta, and the caller
needs both to write its `llm_calls` row. A bare iterator would force the router to reconstruct usage by
counting characters — wrong, and it would silently corrupt ET-9's cost arithmetic.

`generate_stream` is **not** `async def`: it returns the stream object synchronously and awaiting
happens on iteration. That matches both installed SDKs' own shapes and keeps `async with` usable for
guaranteed socket cleanup on cancellation.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Stream both calls** | Puts partially-formed model output in front of the validation path whose contract is that it never sees any, for bytes no human reads. It is the one change in M2 that could weaken ADR-004. |
| **Stream the plan call but buffer it internally before validating** | Then it is not streaming; it is buffering with extra steps, a second code path, and a new way for a partial buffer to escape. All of the risk, none of the benefit. |
| **Show plan tokens in a "thinking" disclosure** | Model-authored JSON shown as if it were reasoning. It invites the user to read structure as intent, and the trace disclosure already shows the *validated* plan — which is the version that is true. |
| **`generate_stream` returns `AsyncIterator[str]`** | Loses usage, `stop_reason` and `provider_request_id`, which arrive after the last delta. The router would have to estimate token counts, and an estimated cost is a wrong cost written to a column that reads as authoritative. |
| **`generate_stream` as `async def` returning an iterator** | Gratuitously different from both vendors' shapes, and it makes the `async with` cleanup path awkward at exactly the moment it matters most — a cancelled turn holding an open socket. |
| **One method with a `stream: bool` flag** | Two return types from one signature, so every call site branches on the flag it just passed. Two methods, two types, no branch. |

## Consequences

* **`llm_calls` gains no column.** A streamed attempt writes one row on completion, with the full
  accumulated text and the real usage from `StreamResult`. A stream that dies mid-flight writes a row
  with `error_kind` and whatever text arrived — a partial answer that cost money is still a row (ET-24).
* **The twelve stages are unchanged.** `llm_io` is emitted once per logical stage as today, and
  `agent_result` fires when the analysis stream completes. **Token frames are not stage events**, in
  exactly the way `llm_calls` rows are not stage events (the ADR-023 argument, reused).
* **⚠️ `stream_options={"include_usage": True}` is mandatory on the OpenAI path.** Verified against the
  installed `openai==3.1.0`: without it the chunks carry no usage, `input_tokens`/`output_tokens` land
  as zero, and **ET-9's cost arithmetic silently under-reports every streamed turn.** ET-25 exists
  solely to catch a regression on that one keyword argument.
* **Two vendors, two stream shapes, one wrapper.** OpenAI is `await create(..., stream=True)` returning
  `AsyncStream`; Anthropic is `async with client.messages.stream(...)` returning an
  `AsyncMessageStreamManager`. `LLMStream` in `providers/base.py` is what stops that difference reaching
  the router — the same job `LLMResponse` already does for the non-streaming path.
* **M9's sentence chunker consumes `StreamDelta`, not raw provider chunks**, so the vendor difference
  never reaches the voice path either.
