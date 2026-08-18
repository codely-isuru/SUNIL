# ADR-020 — A voice turn is three requests sharing one `request_id`; `POST /api/v1/chat` is reused unchanged

**Status:** Proposed (Architect, M9) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §6; `ARCHITECTURE_V1.md` §3.4, §5.3, §11.1, §11.3; `M1_BUILD_PLAN.md` §6
(the frozen contract); `ARCHITECTURE_M9_VOICE.md` §4, §5; ADR-010, ADR-023; FR-203, FR-204.

## Context

M1's `POST /api/v1/chat` is live-verified: a real browser turn in 5.8 s, twelve trace stages, one
allowed tool call, `task=completed`. Its response envelope is the frozen §6 contract and four
components read it — `useTurn`, `ErrorCard`'s four variants, `TraceDisclosure`, and QA's exit
assertions.

M9 must add spoken input and spoken output without forking that.

## Decision

**Three requests, one `request_id` minted by the browser and carried on all three:**

```
POST /api/v1/voice/transcribe    audio  → transcript          (new)
POST /api/v1/chat                text   → answer              (EXISTING, one added field)
GET  /api/v1/voice/speak/{id}    id     → audio/mpeg stream   (new)
```

The only change to the chat surface:

```python
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str | None = None
    input_modality: Literal["text", "voice"] = "text"      # additive, defaulted
```

**And the field is verified, not trusted.** `input_modality="voice"` is accepted only if a
`speech_calls` row exists with `direction="stt"`, `status="ok"`, this `request_id`, and `user_id` equal
to the session owner. Otherwise **422 before any turn machinery runs** — no `messages` row, no
`audit_events` row, no LLM call. Without that check the flag is a free-text provenance claim, and
provenance claims end up in a training corpus (ADR-014's entire argument).

Sharing the `request_id` across three requests is safe **only because the speech legs write no
`audit_events` rows** — `audit_events` has `UniqueConstraint(request_id, seq)` and `LiveTraceContext`
numbers a turn 1…12 from its own counter. See ADR-023.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **One endpoint `POST /api/v1/voice/turn` — audio in, audio out** | Saves two loopback round trips (~60 ms, i.e. nothing) and costs four things: (a) it hides the transcript until the turn is over, when the transcript is the one artefact the owner must be able to check, because an STT error is otherwise indistinguishable from SUNIL misunderstanding him; (b) it forks the frozen §6 response envelope, so two contracts and two failure vocabularies exist for one pipeline; (c) it puts STT + turn + TTS under one `SUNIL_TURN_DEADLINE_S`, and the first thing squeezed on a slow day is the retry budget of the part that matters; (d) it collapses "stop the audio" and "abandon the turn" into one abort, so stopping playback would abandon a turn already completed and paid for. |
| **A separate `POST /api/v1/chat/voice` mirroring the chat route** | Two routes running the same orchestrator, drifting apart on the first bug fixed in one of them. Every guard, every failure mapping and every trace emission duplicated. |
| **Trust `input_modality` from the client** | One line cheaper and it makes the flag meaningless: any caller could label typed text as speech, and the label's only long-lived consumer is a V3 training corpus that cannot re-derive it. A field that cannot be trusted should not be stored. |
| **Infer voice server-side from a `User-Agent` or a cookie** | Guessing where a fact is available. The server *knows*, because the server did the transcription. |
| **A separate `request_id` per leg** | Nothing then joins a voice turn together, and the owner debugging "why did it mishear me" has three unrelated ids. The trace's whole value is that one id reconstructs one interaction. |
| **WebSocket for the whole voice session** | The right shape for V2's barge-in and continuous streaming, and the wrong shape for M9: it replaces a request/response surface that is already authenticated, CSRF-guarded, traced, deadline-bounded and exit-tested with one that is none of those, for a feature that is strictly turn-based. Revisit at R§16 Epic 5, where interruption makes it necessary. |

## Consequences

* Every existing client, fixture and test of `POST /api/v1/chat` keeps working untouched. That
  property is what makes this a one-field change rather than a contract change, and it is why the M1
  exit suite (ET-1…ET-12) is not re-run against a new shape.
* The browser owns the `request_id` for a voice turn, as it already does for a typed turn
  (`useTurn` mints one today; ADR-009 already established the client-supplied-id pattern and
  `RequestContextMiddleware` already validates it as UUID4 or 422).
* Three requests mean three places a session can be checked, and all three check it.
* **Auto-send is a product decision, not an architectural one, and it has a stated expiry.** With
  `SUNIL_VOICE_AUTO_SEND=true` (default) the transcript starts a turn without confirmation. That is
  safe *only* while every reachable tool operation is read-only, which is true in M1 and stops being
  true when M5/M6 land write-capable tools — recorded as **DC-17**, owned by M5, with the real answer
  being the `ASK_USER` approval path (DC-2), not a voice-specific control. The setting exists so the
  default can be flipped in one config edit on that day.
