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
