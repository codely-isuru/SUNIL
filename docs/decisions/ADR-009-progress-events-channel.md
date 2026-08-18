# ADR-009 — M1 ships a real one-way SSE stage-event channel, and it is the designated descope lever

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Escalated by:** UI/UX Designer, `docs/design/M1_CHAT_SPEC.md` Assumption 1, via the Delivery Manager.
**Context refs:** `docs/ARCHITECTURE_V1.md` §8.4, FR-020 (synchronous turn), FR-024 (streaming is M2),
NFR-020 (twelve trace stages), `ROADMAP.md` §33 rule 10.

## Context

FR-020 makes the M1 chat endpoint a single synchronous request/response; token-level streaming is
explicitly deferred to M2 (FR-024). Read literally, the frontend has **no live signal at all** during
a turn that may run to 30 s (ADR-000 Q5).

The Designer compressed NFR-020's twelve backend stages into four visible phases
(Understanding → Planning → Working → Finishing) with an elapsed counter, and refused a fabricated
percentage bar on the grounds that inventing progress contradicts the product's own observability
stance. That design needs a minimal stage-change channel keyed by `request_id`. The Designer also
specified a deterministic client-side timed fallback and asked the Architect to choose.

## Decision

**Build the real channel.** `GET /api/v1/chat/{request_id}/events`, Server-Sent Events, one frame per
stage, plus a terminal `done` frame and a 15 s heartbeat comment.

Three reasons, in order of weight:

1. **It is nearly free.** The twelve events already exist — they are emitted, timestamped and
   persisted for NFR-020/ET-6. Publishing them to an in-process bus and rendering SSE is roughly 90
   lines and one endpoint. The client-side approximation is *not* meaningfully cheaper to build; it
   is only cheaper to design around.
2. **The alternative is dishonest.** A timed stepper claims "Checking EasyClean Workforce…" at t=5 s
   whether or not the tool has been called. In a product whose §33 rule 10 is "every important action
   must be observable", shipping fabricated observability as the first thing a user sees is the wrong
   first impression.
3. **It is cosmetic by construction**, so the risk is bounded. The POST contract is unchanged: still
   synchronous, still returns the full answer (FR-020 untouched, QA's tests unaffected). If the SSE
   connection never opens, drops mid-turn, or the feature is switched off with
   `SUNIL_PROGRESS_EVENTS=false`, the turn completes identically and the answer still arrives.

**And it is the designated descope lever.** If the 2026-08-18 date comes under pressure, task **T12**
is dropped, the flag goes false, and the frontend falls back to the Designer's already-specified
client-side stepper. No redesign, no renegotiation, no surprise. That is agreed in advance rather
than discovered on the last day.

> **Amendment, 2026-08-14 (owner's architecture review §14).** The lever has been pulled in advance:
> **T12 is pre-classified OPTIONAL / post-M1.** It is built only if the vertical slice is green with
> time to spare. `SUNIL_PROGRESS_EVENTS` therefore ships defaulting to `false` and is flipped to
> `true` when T12 lands. The decision *that SSE is the right channel* is unchanged and still stands
> against WebSocket for when it is built.

**Mechanics** (full detail in `ARCHITECTURE_V1.md` §8.4): the browser generates the `request_id`
(FR-004 already permits an accepted-if-supplied ID) and sends it as `X-Request-Id` on the POST and in
the SSE path. `TraceBus` holds per-`request_id`: owning `user_id`, a 64-event replay buffer,
subscriber queues, 5-minute TTL. Whoever arrives first — POST or SSE — creates the channel and claims
ownership; the other must match, or gets 403. Late subscribers get the buffer then live events, so
there is no ordering requirement between the two calls. **The API emits `stage` only**; the 12→4
phase map and every human label live in the frontend, because that is presentation policy the
Designer owns.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Deterministic client-side timed stepper (the Designer's documented fallback)** | Honest about *order*, unable to be honest about *timing*. Kept as the pre-agreed fallback behind the feature flag, not as the primary. |
| **WebSocket (`/ws/conversations/{id}`, per `ROADMAP.md` §24)** | Bidirectional, needs a connection lifecycle, reconnection and message framing, for a strictly one-way stream of twelve small events. SSE reconnects natively, is a plain GET, and needs no client library. §24's WebSocket channels arrive with M2 streaming, where duplex actually earns its cost. |
| **NDJSON streamed from the chat POST itself** | Genuinely elegant: one connection, no correlation, no replay buffer, and client disconnect would give a real cancellation signal. Rejected because it changes the POST response from a JSON object to a stream, which invalidates the exit tests QA is writing from FR-020 *right now* and would need an SRS amendment three days out. |
| **Client polls `GET /api/v1/trace/{request_id}`** | Works with zero new infrastructure, but 1 s polling for 30 s is 30 round trips per turn and a laggy, jerky phase display. |
| **No progress indication at all (a spinner)** | Explicitly rejected by the Designer's brief and by 30 s of dead air. |
| **A fake percentage bar** | M1 cannot know true percent complete. Rejected by the Designer for the right reason and not revisited here. |

## Consequences

- **Debt D-1:** the bus is in-process, so `uvicorn --workers 1` is mandatory. Multi-worker silently
  breaks progress events. Fix is Redis pub/sub, owed at M10 when Redis arrives anyway.
- One extra concurrent connection per turn. Irrelevant at one user; noted because HTTP/1.1 caps
  browsers at ~6 connections per origin.
- `request_id` is now partly client-supplied. It is validated as a UUID4 and scoped to the session's
  `user_id`; a mismatched claim is 403. In a single-user system the check is trivial, but it is
  structurally correct so multi-user does not need to retrofit it.
- The frontend must tolerate the channel being absent. `useTurn()` implements both variants behind one
  interface, so the fallback is a runtime branch rather than a rebuild.

---

## Superseded by ADR-027 — 2026-08-19

**Status: SUPERSEDED.** M2 streams NDJSON frames from the chat POST itself, selected by content
negotiation, and the twelve stage events ride that same stream as `{"type":"stage",…}` frames.

**Nothing is lost, because none of this was built.** T12 was pre-classified OPTIONAL / post-M1 and never
landed — verified 2026-08-19: there is no `StreamingResponse`, no `TraceBus` and no event-stream route
anywhere in `apps/api/sunil/`. `SUNIL_PROGRESS_EVENTS` exists in `settings.py` and nothing reads it; it
is deleted by M2's T46, along with the frontend's `openProgressEvents()` and its `useTurn` call site,
which point at an endpoint that never existed (debt D-22).

**What this ADR got right and ADR-027 keeps:** the events are already produced, timestamped and
persisted for NFR-020, so publishing them costs almost nothing; a fabricated progress display would
contradict §33.10; the API sends `stage` enums only and the 12→4 phase map stays in the frontend; and
progress must never be able to change the turn's outcome.

**What ADR-027 changes, and why:** this ADR's `TraceBus` — a replay buffer, an ownership claim, a TTL
and a documented POST/SSE race — exists **only because the stream was a different connection from the
work**. Streaming from the POST deletes that machinery rather than solving it, and it yields a real
cancellation signal, which this ADR could not.

**And ADR-027 accepts the option this ADR rejected.** Its own rejected-alternatives table said of
streaming from the POST: *"Genuinely elegant … Rejected because it changes the POST response from a
JSON object to a stream, which invalidates the exit tests QA is writing from FR-020 right now and would
need an SRS amendment three days out."* Content negotiation answers that objection, and the three-day
deadline that made it decisive has passed.
