# ADR-019 — STT and TTS live in `sunil/speech/`, not in the Model Router

**Status:** Proposed (Architect, M9) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §6, §14 Epic 11; `ARCHITECTURE_V1.md` §4.1, §4.2, §4.6, §9.3, §13.1;
`ARCHITECTURE_M9_VOICE.md` §2, §3; ADR-003; FR-040, NFR-002, NFR-007.

## Context

`ROADMAP.md` §6 says voice is "only another interface" and that "the reasoning model does not need to
be the same service used for STT or TTS", and its diagram puts speech-to-text *above* SUNIL and
text-to-speech *below* it, with the Model Router in between. It never says where the adapters live.

The tempting answer is the Model Router. It already owns "call a model at a vendor with a key",
already has capability-keyed selection, bounded retry with jitter, a turn-deadline check and per-attempt
cost persistence. Adding `LLMPurpose.STT` and `LLMPurpose.TTS` is an afternoon's work.

## Decision

**STT and TTS adapters live in a new sibling package `sunil/speech/`, with their own `SpeechProvider`
protocol, their own registry, their own capability file (`config/speech.yaml`) and their own
persistence table (`speech_calls`). They are not `LLMProvider`s, they are not selected by
`ModelRouter`, and nothing in `core/`, `agents/` or `tools/` may import them.**

The vendor-neutrality *rule* (§4.1 — callers name a capability, never a vendor) is kept and applied to
speech. What is not shared is the lookup.

Four reasons, in decreasing order of force:

1. **The `LLMProvider` contract is text→text with structured output.** Carrying audio would make
   `LLMRequest.messages` a union that the plan validator, `ask_model`, the retry policy and the
   redaction hook on `llm_calls.request_messages` must all narrow — a breaking change to the one
   interface ADR-003 exists to keep stable, to reuse ~40 lines of retry code.
2. **The cost model is different, and `llm_calls` cannot express it truthfully.** Verified against the
   installed `openai==3.1.0`: transcription bills by audio duration (`UsageDuration.seconds`, and
   `Transcription.usage` is `Optional`), and synthesis returns raw binary with **no usage object at
   all**. `llm_calls.input_tokens`/`output_tokens`/`cost_micro_usd` are `NOT NULL`, so speech rows
   would carry invented numbers or zeros — and §13.1 defines a turn's cost as the sum over its
   attempts, which a zero row silently falsifies.
3. **Reasoning capabilities and media capabilities are selected on different grounds.** A reasoning
   capability is chosen by the purpose of a turn stage; a speech capability by the interface the
   request arrived on. Sharing one registry couples them: repointing `general_reasoning` at a local
   model in V2 would drag speech with it, or force an `if capability.is_speech` branch into the router.
4. **It keeps TB3 honest.** `AgentContext` grants exactly `call_tool`, `ask_model`, `memory`, `trace`.
   If speech were a provider, `ask_model` would be one enum value from an agent spending money on
   synthesis — and from reaching the transcription API's free-text `prompt=` parameter, which steers
   the model and would give attacker-controlled tool output a path into a transcript.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Add `LLMPurpose.STT` / `LLMPurpose.TTS` and extend `LLMProvider`** | Reason 1 above. It is the cheapest thing to write and the most expensive thing to own: every existing consumer of `LLMRequest`/`LLMResponse` inherits a union it does not need, forever, and `llm_calls` inherits two cost models it cannot express. |
| **Keep the Model Router but add a second method `transcribe()` to `LLMProvider`** | Every text-only provider then implements two methods it cannot honour, or the protocol grows `supports_audio` and every call site grows a branch. A capability an implementation cannot satisfy is not an interface, it is a suggestion. |
| **Put `speech/` inside `providers/` as `providers/speech/`** | Keeps the import-boundary allow-list unchanged (a real, small benefit) but makes "provider" mean two different things in one package, and puts media adapters inside the package whose name the whole codebase reads as "LLM vendor". The allow-list change is one tuple entry (ADR-019 consequence 3); the naming confusion is permanent. |
| **A generic `ExternalService` abstraction covering LLM, speech and future vendors** | The two things have nothing in common except "HTTP with a key". A shared base would be a class with one useful method and four conditionals, invented before the third case exists. YAGNI, and §14.3's standing bias against machinery. |
| **No abstraction at all — call the SDK from the route** | Then the route holds the key, the retry policy, the cost arithmetic and the capture decision, and swapping vendor (which R§6 explicitly anticipates) is a rewrite of an HTTP handler. It also makes the "no vendor named outside the adapter package" import rule unenforceable. |
| **Share `core/routing/retry.py` between the two packages** | Creates an import edge from `speech/` into `core/routing/`, which is exactly the coupling this ADR removes. ~30 lines of duplication is the cheaper half of the trade, and the two retry policies are already different (speech retries once; the router retries three times with a turn-deadline check speech has no equivalent of). |

## Consequences

1. `sunil/speech/` is a **second vendor-adapter package**. The DC-10 import rule
   *"only `sunil/providers/` imports a vendor SDK"* becomes *"only `sunil/providers/` and
   `sunil/speech/` import a vendor SDK"*, and the parametrised `test_dc10_rules_are_all_covered` list
   moves with it in the same change (T35).
2. A **new** import rule is added: only `sunil/api/routes/voice.py` may import `sunil.speech.*`. This
   is R§6's "voice is only another interface" turned into a test.
3. Roughly 30 lines of retry/classification logic are duplicated between the two packages, knowingly.
4. `speech_calls` is a new table (migration `0002`) rather than rows in `llm_calls`. A turn's total
   spend is therefore `sum(llm_calls) + sum(speech_calls)`, and any future cost view (M3, NFR-031) must
   read both. Recorded here so it is not discovered by a cost report that under-reports voice.
5. Adding a second speech vendor later follows §4.6's recipe unchanged: implement `SpeechProvider`,
   one line in `speech/registry.py`, one entry in `config/speech.yaml`. That is how R§6's "need not be
   the same service" is honoured.

---

## Amendment 1 — the second speech vendor strengthens this decision

**Date:** 2026-08-19 · **Origin:** the owner's decision to move synthesis to ElevenLabs (ADR-026)
**Status:** Accepted · **Applies to:** reason 2 and reason 3 of the decision. Nothing is withdrawn.

The Delivery Manager asked the right question: does a second speech vendor strengthen this ADR's
argument or complicate `speech_calls`? **It strengthens it, and the complication it appeared to add
turned out to be a simplification.**

### Reason 2 (the cost model) gets stronger, and the schema gets simpler

The original argument was that `llm_calls` cannot express speech billing truthfully because
transcription bills by audio duration and synthesis had no usage object at all. With ElevenLabs there
are now **three vendor/leg combinations across two billing units** — audio seconds for OpenAI
transcription, characters for ElevenLabs synthesis (and characters again for OpenAI synthesis, the
option kept commented in config).

Two units in one table is not a problem; it is a column. `speech_calls` gains `billing_unit`
(`audio_second | character`) and `billed_units`, `config/speech.yaml` names the unit and the price per
unit beside the model, and cost is `billed_units × unit_price` — **one line, no vendor branch**.

Note what that removes. Under a single vendor, `SpeechService` would have carried an
`if direction == "stt"` branch to pick which column to multiply. The second vendor deleted the branch,
because it forced the unit to be *named data* rather than *inferred from the leg*. **A second
implementation making an abstraction simpler is the strongest available evidence the abstraction was
drawn in the right place.**

Had speech gone into `llm_calls` instead, this same pressure would have produced a `billing_unit`
column on the table that carries every reasoning call — a column meaningless for 100% of the rows that
were there first.

### Reason 3 (capability indirection) stops being theoretical

The original text argued that reasoning capabilities and media capabilities are selected on different
grounds and should not share a lookup. That was an argument about a hypothetical. It is now the
mechanism by which a live vendor change costs **one adapter module and one block of YAML**, with zero
changes to `core/`, `agents/`, `tools/`, or even `api/routes/voice.py` — which names capabilities, not
vendors. `ROADMAP.md` §6's sentence *"the reasoning model does not need to be the same service used for
STT or TTS"* is now demonstrated rather than asserted, and so is the stronger version it implies:
**the STT service need not be the TTS service either.**

### What genuinely does get harder, said plainly

* **Two failure domains.** Transcription can succeed while synthesis is down. FR-207 (a synthesis
  failure never fails the turn) moves from defensive to load-bearing.
* **Two keys, two base URLs, two guards** — ADR-022 Amendment 1.
* **Two auth header shapes.** OpenAI uses `Authorization: Bearer`; ElevenLabs uses `xi-api-key`. The
  `SpeechProvider` protocol never sees either — each adapter owns its own client construction, which
  is what keeps this a two-line difference rather than a conditional.
