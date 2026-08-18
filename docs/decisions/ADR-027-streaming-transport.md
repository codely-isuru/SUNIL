# ADR-027 — Stream NDJSON from the chat POST, selected by `Accept`. Not a side channel, and not WebSocket.

**Status:** Proposed (Architect, M2) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Supersedes:** ADR-009 (progress-events channel). **Contradicts:** `REQUIREMENTS_V1.md` FR-024 and
`ROADMAP.md` §24, argued in full below.
**Context refs:** `ARCHITECTURE_V1.md` §8.4, §11.1, §11.3, V-9; ADR-008, ADR-010;
`ARCHITECTURE_M2_STREAMING.md` §3, §4; FR-020, FR-024, NFR-061; DC-7, D-4.

## Context

M2 must deliver SUNIL's answer to the browser as it is generated. Three things constrain the choice:

1. **`POST /api/v1/chat` is the frozen §6 contract**, and ET-1 … ET-12 are written against it. Anything
   that changes its default response invalidates a passing exit suite.
2. **`REQUIREMENTS_V1.md` FR-024 says "over WebSocket"**, and `ROADMAP.md` §24 lists
   `/ws/conversations/{id}`. ADR-009 accepted that anticipation in writing: *"§24's WebSocket channels
   arrive with M2 streaming, where duplex actually earns its cost."*
3. **ADR-009 specified a separate SSE channel** (`GET /api/v1/chat/{request_id}/events`) with a
   `TraceBus`, a replay buffer, an ownership claim and a TTL. **It was never built** — verified: there
   is no `StreamingResponse`, no `TraceBus` and no event-stream route anywhere in `apps/api/sunil/`.
   `SUNIL_PROGRESS_EVENTS` exists in `settings.py` and nothing reads it.

So this decision is not constrained by working code. It is constrained by two documents that both
anticipated an answer, and by an exit suite that must keep passing.

## Decision

**The chat POST gains a streaming representation, selected by content negotiation.**

```
Accept: application/json      (default)  → today's ChatResponse envelope, byte-for-byte
Accept: application/x-ndjson             → a stream of newline-delimited JSON frames
```

Frames are `{"type": …}` objects, one per line: `stage`, `token`, `heartbeat`, and exactly one terminal
`done` **carrying the complete envelope the JSON response would have had**. A client that ignores every
frame except `done` behaves exactly like today's client.

**Streaming is a projection, never the source of truth.** The tokens are an early view of a value the
final frame delivers authoritatively. A dropped, misparsed or duplicated token frame cannot corrupt the
answer — the same property that made ADR-009 safe, kept for the same reason and now doing more work.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **A separate SSE channel (ADR-009's own design)** | Every piece of its machinery — a 64-event replay buffer, an ownership claim keyed by `user_id`, a 5-minute TTL, and a documented race in which "whoever arrives first creates the channel" — exists **only because the stream is a different connection from the work**. Streaming from the POST deletes all of it rather than solving it. It also gives no cancellation signal: a dropped SSE connection says nothing about whether the POST should stop. |
| **WebSocket, per FR-024 and R§24** | Duplex earns its cost when the client sends *application messages* mid-stream. M2 has exactly one client→server signal — *stop* — and HTTP already expresses it as a disconnect. Against that, a socket costs a connection lifecycle, a reconnect policy, a resubscribe protocol, and a **bespoke CSRF control**: browsers do not apply CORS to WebSocket handshakes, so `X-SUNIL-Client` (ADR-008's control) cannot be sent and a hand-written `Origin` check becomes the only defence. Replacing three mechanisms that already work with one that must be written correctly is not progress. |
| **SSE framing (`event:`/`data:`) from the POST** | An `EventSource` cannot issue a POST, so the client hand-parses either way. Given that, one JSON object per line is simpler to emit and to parse than SSE framing, and the frames need a `type` discriminator regardless. NDJSON also cannot be mistaken for something `EventSource` will consume. |
| **Always stream; drop the JSON representation** | Invalidates ET-1 … ET-12 and FR-020's "within the same request/response cycle" for no benefit. Content negotiation costs one `if` and keeps a passing exit suite passing. |
| **A `?stream=true` query parameter instead of `Accept`** | Representation selection is what `Accept` is for, and a query parameter makes the same resource look like two. It would also mean the streaming and non-streaming forms could be cached differently by accident. |
| **A second endpoint, `POST /api/v1/chat/stream`** | Two routes running one pipeline, drifting apart at the first bug fixed in one of them — the same argument ADR-020 made against a separate voice turn endpoint. |
| **Chunked plain text (no framing)** | Cannot carry stage events, cannot carry the terminal envelope, and gives the client no way to distinguish an answer fragment from a control message. Framing is what makes one connection able to do two jobs. |
| **Keep ADR-009's channel *and* add token frames to it** | Two connections, all the correlation machinery, and a cancellation story that still does not work. Strictly worse than either single-connection option. |

## Contradicting the SRS and the roadmap — the argument, not the omission

`REQUIREMENTS_V1.md` FR-024 says the response is streamed **"over WebSocket"**. That is a design
decision written into a requirement. What the owner needs is that *the answer appears as it is
produced*; which wire carries it is an architectural choice, and freezing it in the SRS means it cannot
be revisited without an SRS amendment — friction that keeps bad transports in production.
`ARCHITECTURE_M2_STREAMING.md` §11.1 rewords FR-024 to state the need and leave the transport to this
ADR.

`ROADMAP.md` §24's `/ws/…` channels are **not wrong forever.** They become right when SUNIL pushes
*unsolicited* events to an idle client: a scheduled task finishing (M10), an agent needing approval
(M5), a second device watching a shared conversation. None of those exist yet, and none is in V1's
current milestone set before M5. Recorded as deviation **V-10** so the next reader of §24 finds this
argument instead of re-deriving it — and so that when M5 lands, the question is reopened deliberately.

## Consequences

1. **ADR-009 is superseded and `SUNIL_PROGRESS_EVENTS` is retired.** Nothing is lost — T12 was never
   built. The frontend's `openProgressEvents()` and its `useTurn` call site are dead code pointing at
   an endpoint that never existed, and they are removed as part of M2 (debt D-22), not left to rot.
2. **The twelve stages now arrive as `stage` frames on the same stream as the answer.** The 12→4 phase
   map stays in `apps/web/src/lib/phases.ts`; the API still sends enums and numbers only (§11.2). The
   `WorkIndicator` gets real events instead of the timed fallback, without a redesign — which is the
   property ADR-009 built it for.
3. **Cancellation becomes available** (ADR-029): a client abort is a disconnect, and a disconnect is a
   cancellation signal. That closes DC-7 and debt D-4.
4. **One envelope builder, two representations.** The `done` frame and the JSON body are built by the
   same function, so they cannot drift. A test asserts a streamed turn and a non-streamed turn against
   the same fixture produce identical envelopes (ET-19/ET-20).
5. **`BaseHTTPMiddleware`'s contextvar scope ends when `call_next` returns**, which is before the body
   has finished streaming — so log lines emitted late in a stream lose `request_id` unless the
   generator re-binds it. Specified in `ARCHITECTURE_M2_STREAMING.md` §7 rather than discovered by
   grepping a slow turn's logs and finding nothing. Debt **D-20**.
