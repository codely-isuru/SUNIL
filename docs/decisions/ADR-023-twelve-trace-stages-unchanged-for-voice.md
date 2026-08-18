# ADR-023 — The twelve trace stages are unchanged by voice; `speech_calls` is a sibling record, not a stage

**Status:** Proposed (Architect, M9) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Context refs:** `ARCHITECTURE_V1.md` §3.4, §8.1, §8.5; `M1_BUILD_PLAN.md` §6 (the frozen contract);
`ARCHITECTURE_M9_VOICE.md` §4.4, §10; ADR-009, ADR-020; NFR-020, ET-6.

## Context

NFR-020's twelve stages are the spine of everything SUNIL claims about itself. `TraceStage` is a frozen
enum with one call site per member; `LiveTraceContext.emit()` is the only way a stage advances and
raises `DuplicateStageEmission` on a second emission of the same stage; `audit_events` carries
`UniqueConstraint(request_id, seq)` and a CHECK constraint over the enum; and ET-6 asserts
`set(stages_emitted) == set(TraceStage)`, in order, **from `audit_events` alone**.

M9 adds two real operations to a turn — transcription before it and synthesis after it — and has to
decide whether they are stages.

## Decision

**They are not. A voice turn emits exactly the same twelve stages, in the same order, with the same
names, as a typed turn. `TraceStage` is not extended and ET-6 is not touched.**

The reasoning is a structural observation, not a convenience: **neither `llm_calls` nor `tool_calls` is
a stage either.** They are sibling records that stages point at. `speech_calls` is a third sibling of
exactly the same kind. `audit_events` holds a turn's *reasoning* spine; the sibling tables hold what
each stage actually did, at what cost, over how many attempts.

```
speech_calls   direction=stt   request_id=R   latency_ms=940     ← before the turn
audit_events   seq 1..12       request_id=R                      ← the turn, unchanged
speech_calls   direction=tts   request_id=R   latency_ms=610     ← after the turn
```

One `request_id` joins all three; `GET /api/v1/trace/{request_id}` reassembles them in timestamp order;
NFR-020's actual claim — reconstructable from stored records alone — holds for a voice turn exactly as
for a typed one.

**Two `detail` keys are added to §3.4's contracted table:**

| Stage | New contracted keys |
|---|---|
| `message_received` | `input_modality` (`"text"`\|`"voice"`); **when voice**: `stt_ms`, `audio_ms`, `stt_model` |
| `final_response` | `output_modality_requested` (`"text"`\|`"voice"`) |

`final_response` carries **no** `tts_ms`, because stage 12 fires before synthesis is requested and this
architecture does not put a number in a field that cannot be known yet. TTS timing lives on the
`speech_calls` row, written when it is actually known. **The transcript is not put in `detail`** — it is
the message, and it lives in `messages.content` (T-32's rule, unchanged).

**Consequence that makes ADR-020 work:** sharing one `request_id` across three HTTP requests is only
safe *because* the speech legs write no `audit_events` rows. If they did, their `seq` values would
collide with the turn's 1…12 on `UniqueConstraint(request_id, seq)` — an `IntegrityError` that would
have appeared intermittently, under load, long after the design was settled.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Add `speech_transcribed` / `speech_synthesised` as stages 0 and 13** | ET-6 asserts `set(emitted) == set(TraceStage)`. New members become mandatory for **every** turn, so every typed turn fails ET-6 — or ET-6 weakens to "at least the twelve", which is precisely the assertion that stops catching a *missing* stage. It also forces a change to `apps/web/src/lib/phases.ts`'s 12→4 map in a milestone whose frontend has no test runner. |
| **Add the two stages but make them optional in ET-6** | The same weakening, wearing a smaller hat. An exit test with an "unless" clause is an exit test that will one day pass while the thing it guards is broken. |
| **Emit the existing twelve twice, once per leg** | Violates §3.4's "each stage is emitted at most once per turn", which `LiveTraceContext` enforces structurally. It is also false: nothing was planned, permitted or tooled during transcription. |
| **Give each leg its own `request_id`** | Nothing then joins a voice turn together, and the owner debugging "why did it mishear me" holds three unrelated ids. One id reconstructing one interaction is the whole value of the trace. |
| **Share the `request_id` *and* write audit rows from the speech legs** | The `UniqueConstraint(request_id, seq)` collision above. Discovered late, intermittently, and it would look like a concurrency bug. |
| **Put speech timings in `audit_events.detail` of an existing stage retroactively** | Would require updating a row after it was written. `audit_events` is an append-only record in spirit, and the one property T-33/T-34 lean on is that a stage row means "this happened, then". Mutating one to add a later fact erodes that for a display convenience. |
| **A parallel `voice_events` trace table** | A second spine to keep in order, reconcile and test, for two rows. `speech_calls` already carries timestamps. |

## Consequences

* **ET-6 is unchanged and untouched by M9.** A new exit test, **ET-13**, asserts the equivalence
  directly: the same request typed and spoken produces the same twelve stages in the same order, and
  the spoken turn has exactly twelve `audit_events` rows. That is the assertion that catches anyone
  later "helpfully" adding a stage.
* `apps/web/src/lib/phases.ts` — the 12→4 phase map, `STAGE_NAMES`, `STAGE_TO_PHASE` — needs **no
  change**. The `WorkIndicator` behaves identically on a voice turn.
* A turn's total spend becomes `sum(llm_calls) + sum(speech_calls)`. `ChatResponse.usage` covers the
  reasoning legs only; the voice legs are visible in the trace read endpoint and in `speech_calls`. Any
  future aggregate cost view (M3, NFR-031) must read both tables — recorded here so it is not
  discovered by a report that under-states voice spend.
* `TraceDisclosure` gains one line sourced from `speech_calls`, rendered **below** the twelve and
  visually distinct from them, because it is not a stage.
