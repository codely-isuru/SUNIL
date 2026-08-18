# ADR-024 — M9 removes the silence, not the wait; sentence-level pipelining waits for M2

**Status:** Proposed (Architect, M9) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Context refs:** `ARCHITECTURE_V1.md` §5, §8.4; `design/M1_CHAT_SPEC.md` §5.3, §5.4;
`ARCHITECTURE_M9_VOICE.md` §9; ADR-009; NFR-060, NFR-061, NFR-062, BL-001, BL-009.

## Context

A measured M1 turn is **5.8 s**. That is comfortable when reading and long when talking to something:
in a text turn the user is reading, in a voice turn the user is waiting in silence. The full voice
path — capture flush, upload, STT, turn, synthesis, playback start — comes to roughly **6.9–8.5 s**
from release to the first word of the answer.

The honest fixes are architectural, not cosmetic. There are three candidates and only two of them are
available to M9.

## Decision

**M9 does not make the wait shorter. It makes the wait stop being silent, and it takes the one real
latency win that does not need streaming reasoning.** Four measures, in the order they fire:

1. **An earcon on release (~50 ms).** A ~40 ms `AudioContext` oscillator blip confirming capture. No
   network, no vendor, no dependency, no cache — it works when everything else has failed. **Time to
   first feedback: ~7.5 s → ~0.05 s.**
2. **The transcript on screen at ~1 s.** The first *meaningful* feedback, and the one that lets the
   owner tell "it misheard me" from "it's broken" before the answer arrives.
3. **Streamed synthesis.** `client.audio.speech.with_streaming_response.create(...)` +
   `stream_format="audio"` + a `StreamingResponse` forwarding chunks + native `<audio>` progressive
   playback. Verified achievable from the installed `openai==3.1.0` — `AsyncAPIResponse.iter_bytes()`
   is an async generator, whereas the plain `await create(...)` path's `iter_bytes()` is synchronous
   over an already-buffered body and would look like streaming while streaming nothing. **Estimated
   0.3–0.8 s to first audio byte instead of 1.0–2.5 s to a complete file.**
4. **Synthesis starts the instant the chat POST resolves** — not after React paints.

**And one thing M9 deliberately does not do: speak progress.** *"Working out a plan…"* spoken over a
6 s wait costs a TTS round trip per phase, talks over the user, and — the real objection — asserts
progress the system does not measure. `M1_CHAT_SPEC.md` §5.3 already rejected a percentage bar on
exactly this ground: *"M1 cannot know true % complete, and a fake percentage would be dishonest."* The
argument is stronger, not weaker, when it is said aloud. The existing four-phase `WorkIndicator` stays
visible and silent.

**What needs M2, stated so nobody promises it.** Synthesising the answer *before the whole answer
exists* requires token streaming from the reasoning model, which is **BL-001 / M2 / NFR-061**. With it,
incoming text is chunked at sentence boundaries and each sentence is synthesised while the next is
generated, so speech begins at roughly the first sentence: **release → first spoken word ≈ 2.5–3.5 s
instead of ~7 s.** That is the change that makes it feel like a conversation, and **M9 cannot deliver
it.** `REQUIREMENTS_V1.md` already records BL-009 as depending on BL-001; this ADR is what that
dependency means in practice.

**The seam M9 leaves so M2 is additive:**

* `SpeechProvider.synthesize(text: str)` today; M2 adds `synthesize_stream(chunks: AsyncIterator[str])`
  beside it. The protocol grows a method; nothing existing changes signature.
* **The client side is already built.** `<audio>` progressive playback over a chunked `audio/mpeg`
  response does not care whether the server forwards one upstream synthesis or concatenates six. M2's
  work is entirely server-side.
* `speech_calls` already carries `attempt` and per-call cost, so N sentence-level syntheses are N rows
  and the cost arithmetic stays true with no schema change.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Speak the four progress phases** | Costs a synthesis round trip per phase, occupies the audio channel the answer needs, and makes a progress claim the system does not measure — the argument `M1_CHAT_SPEC.md` §5.3 already made against a percentage bar. |
| **A looping "thinking" hum or music bed** | Fills the silence without conveying anything, cannot be interrupted cleanly without the barge-in machinery that is V2, and is the audio equivalent of a fake progress bar. |
| **Ship voice only after M2** | The cleanest-sounding option and it defers a working interface for a milestone. The owner asked for voice now; M9's measures take the *silence* to ~0.05 s, which is the part that is actually broken, and M2 then improves the same architecture without changing its shape. Sequencing is the owner's call — it is listed as an open question in `M9_BUILD_PLAN.md` §8. |
| **Pre-synthesise a bank of stock answers** | Only works for answers known in advance, which is every answer this system does not give. |
| **Play the acknowledgement on *release*, before transcription** | Fastest possible, and it says "I heard you" before SUNIL knows whether it did. Playing it when the transcript exists — and showing the transcript at the same instant — makes it true. Honesty over 900 ms. |
| **Client-side STT (Web Speech API) to skip the upload** | Would cut leg 4 to near zero, and in Chromium it ships the audio to Google's servers anyway — a second, unguarded, undeclared egress path that ADR-022's whole control would not cover. It is also unavailable or divergent across browsers. |
| **Buffer the whole synthesis and send one response** | Simpler by a few lines and gives up the one real latency win available without M2. |

## Consequences

* **Five of the eight legs in `ARCHITECTURE_M9_VOICE.md` §9.1 are estimates**, because this environment
  has no network access and no key in the shell. They are labelled ESTIMATE rather than presented as
  measured — the same discipline `config/models.yaml` applies to OpenAI's pricing, where zeros are
  written rather than guesses. **T37 measures all five over 10 runs and edits that table in place**,
  reporting median and maximum *per leg* as §5.2 requires. Debt **D-16**.
* **One assumption in this ADR is unverified and material:** whether `stream_format="audio"` actually
  yields early bytes in practice. If it does not, leg 7 collapses into leg 7b and the total moves by
  ~1–1.7 s. Both rows are in §9.1's table for that reason, and T37 answers it explicitly.
* NFR-062 is written as a *per-leg* median-and-maximum requirement, never a single figure, because a
  single figure over six legs hides which one regressed.
* Barge-in, wake word and offline voice remain V2 (R§16 Epic 5). M9 gives a stop button, not voice
  interruption.

---

## Amendment 1 — M2 ships first, and my "~2.5–3.5 s" was wrong

**Date:** 2026-08-19 · **Origin:** the owner's decision to build M2 before M9, taken on this ADR's
own §9.3 argument · **Status:** Accepted · **Applies to:** the "what needs M2" section. The
recommendation to build streaming first stands; **the number I used to justify it does not.**

### The correction, first, because it may change the owner's mind

This ADR said that with M2's token streaming, *"release → first spoken word ≈ 2.5–3.5 s instead of
~7 s."* **That estimate is wrong, and it is wrong in the direction that flatters my own
recommendation.**

It assumed the answer begins generating when the turn begins. It does not. An M1 turn is
**three sequential legs** (ADR-015, §3.4): a plan call, a tool call, then the analysis call — and the
analysis call *is* the answer. Token streaming accelerates only the third leg. Everything before the
first token of the analysis is untouched by it.

```
release ─ 0.1s ─ upload ─ STT ~1.0s ─┬─ plan ──── tool ──── analysis ─────────────┐
                                     │   (streaming changes nothing here)  ^      │
                                     │                                     |      │
                                     └─────────────────────── first token ─┘      │
                                                       first SENTENCE ─ TTS ─ speak
```

Honest revised arithmetic, with every component labelled:

| Leg | Time | Basis |
|---|---|---|
| Release → blob → upload | 0.06–0.18 s | ESTIMATE |
| STT (OpenAI `gpt-4o-mini-transcribe`) | 0.6–1.5 s | ESTIMATE |
| Plan call + GitHub read + analysis-to-first-**sentence** | **3.0–4.5 s** | **Derived, not measured** — see below |
| TTS to first byte (ElevenLabs `eleven_flash_v2_5`, ~75 ms model latency) | 0.2–0.5 s | ESTIMATE, ADR-026 |
| Playback start | 0.05–0.15 s | ESTIMATE |
| **Release → first spoken word** | **≈ 3.9–6.8 s; ~5.3 s typical** | |

Against ~7.5 s without streaming, that is a **~2 s improvement, not a ~4 s one.**

**And the "3.0–4.5 s" row is the weakest number in this document.** The 5.8 s turn was measured as a
*total*; the split between plan, tool and analysis was never measured separately, so that row is
apportioned from §5.1's budget model rather than observed. It is the single most valuable measurement
M2 can take, and it is now a task in its own right (`M2_BUILD_PLAN.md` T27a), taken **before** the
streaming work rather than after, so the design is aimed at the leg that is actually large.

### The floor, and why no amount of streaming goes below it

`STT + plan + tool + first sentence of analysis + TTS-first-byte`. Roughly **4–5 s**, and it is set by
the **two-LLM-stage pipeline shape** (ADR-015), not by the transport. Streaming cannot cross it. Only
changing what happens before the answer exists can — and the two candidates are M6's agent loop
(which makes it *worse*) and speaking something true earlier.

### The one new option M2 creates, and how it differs from what this ADR rejected

The original decision rejected speaking progress, on the ground that *"a spoken phase label is a claim
about progress that the four-phase model deliberately does not make."* That rejection stands.

**Speaking a fact read from a validated plan is a different thing.** At `plan_created` — roughly
2.5 s into the turn — SUNIL knows, from a plan that has passed all five validation layers, which
project it is about to check. *"Checking the workforce repo."* asserts nothing the system does not
know; it is the identical fact the `WorkIndicator` already renders on screen as *"Checking {Project}…"*
from `plan_created.detail.project_display_name` (§3.4). It fills the 2.5 s → 5.3 s gap with something
true, and it costs one short synthesis of ~30 characters.

| Rejected (still rejected) | Permitted (new) |
|---|---|
| *"Working out a plan…"*, *"Putting your answer together…"* | *"Checking the workforce repo."* |
| A claim about **progress**, which nothing measures | A statement of **fact**, from a validated plan, already displayed |

It is **optional** and it is the descope lever it replaces: if it is dropped, the earcon plus the
on-screen transcript still carry the interaction. It must never be spoken when the plan was rejected,
and it must be cancelled if the answer's first sentence is ready before it finishes.

### What the reordering costs M9, and why the owner's decision is still right

**Sentence-level pipelining moves from "M2's additive work" into M9's own scope.** When M9 is built,
streaming will already exist, so M9 must consume it on day one rather than buffer the answer and
synthesise once. That is a real scope increase to M9 — a sentence-boundary chunker, a
`synthesize_stream()` adapter path, and a chunked response whose upstream is N syntheses rather than
one — and `M9_BUILD_PLAN.md` carries it.

**The decision is nevertheless right, and on firmer ground than the latency number.** Retrofitting
pipelining into a shipped M9 means rewriting the synthesis path, the response path and the client's
playback assumptions after they have exit tests pointed at them. Doing it once is cheaper than doing
it twice, and that argument does not depend on whether the saving is 2 s or 4 s.

**But the owner reversed the order to get voice "landing once at ~3 s", and it will not be ~3 s.** He
should see the corrected number and confirm, because if ~5.3 s and ~7.5 s feel equally like waiting,
then shipping M9 first and taking the streaming benefit later is the better trade and this
amendment is the argument for reopening it.
