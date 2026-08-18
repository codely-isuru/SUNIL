# SUNIL M2 — Streaming and cancellation: architecture

**Author:** Solution Architect, Minions Team 18 · **Status:** for owner review (Gate M2) · **Date:** 2026-08-19
**Parent architecture:** [`docs/ARCHITECTURE_V1.md`](ARCHITECTURE_V1.md) — `§n` below refers to *that*
document unless prefixed `R§` (roadmap) or `M2§` (this one).
**Plan of record:** [`docs/ROADMAP.md`](ROADMAP.md) — R§14 Epic 2, R§23 Step 3, R§24 (API surface).
**Requirements:** [`docs/REQUIREMENTS_V1.md`](REQUIREMENTS_V1.md) — **FR-024 is one line, SHOULD, and it
names a transport.** M2§1 says why that is a defect and what the set must become.
**Decisions:** ADR-027 … ADR-029 in [`docs/decisions/`](decisions/). **Supersedes ADR-009.**
**Threat model:** [`docs/THREAT_MODEL.md`](THREAT_MODEL.md) §13 (added by this milestone).
**Downstream:** [`docs/ARCHITECTURE_M9_VOICE.md`](ARCHITECTURE_M9_VOICE.md) — M9 was reordered to build
*after* this, so M2's stream is what M9's sentence chunker consumes.

---

## 0. Why this is the next build, and what it is honestly for

The owner reversed the build order on 2026-08-19 after reading M9§9.3: he would rather voice land once
on a streaming foundation than land on a buffered one and be retrofitted. M2 is therefore the next
build, and M9 follows it.

**M2 does not make a turn faster.** A turn takes what it takes — 5.8 s measured, unchanged by anything
in this document. What M2 changes is *when the user learns something*: first frame at ~0.1 s instead of
~5.8 s, and the answer arriving word by word instead of all at once. That is a perception change, and
saying so plainly is the point of this section. Anyone reading "streaming" as "faster" will be
disappointed by the measurement in M2§8.

Three rules, inherited unchanged:

1. **Deterministic code holds the privilege.** Streaming changes how bytes reach the browser. It does
   not change what may run: the plan is still validated whole before any tool executes.
2. **Nothing is claimed that the code will not have.** M2§10 lists what this milestone does not
   deliver, including two requirements the SRS assigns to M2 that M2 does not build (M2§1.3).
3. **Every SDK fact was read from — and executed against — the installed package.** Four findings,
   M2§9.

---

## 1. The requirement gap — worse than FR-200's, in a specific way

`REQUIREMENTS_V1.md` gives M2 four rows and one NFR:

| ID | Pri | Statement |
|---|---|---|
| FR-023 | SHOULD | The owner can continue an existing conversation by ID; prior messages in that conversation are loaded as context for the Orchestrator. |
| **FR-024** | **SHOULD** | **SUNIL's response is streamed to the chat UI over WebSocket as it is generated.** |
| FR-025 | SHOULD | The API exposes retrieval of conversation list and message history. |
| NFR-061 | COULD | Streamed responses begin within 3 seconds of request receipt (perceived latency). |

**FR-200 was too thin. FR-024 is thin *and* prescriptive, which is worse.**

### 1.1 It names a transport, which is a design decision wearing a requirement's clothes

"over WebSocket" is not a statement of what the owner needs; it is an implementation choice smuggled
into the SRS, and it happens to be the wrong one (ADR-027). A requirement should say *the owner sees
the answer appear as it is produced*. Which wire carries it is mine to decide and to defend — and if
the SRS fixes it, the decision cannot be revisited without an SRS amendment, which is exactly the
friction that keeps bad transports in production.

`ARCHITECTURE_V1.md` already flagged this once: **V-9** records that "M1 progress uses SSE, not §24's
`/ws/…` WebSocket channels", and ADR-009 wrote that "§24's WebSocket channels arrive with M2 streaming,
where duplex actually earns its cost." **I re-examined that and it does not earn it** — M2§3. This
document is where that anticipation is withdrawn rather than inherited.

### 1.2 NFR-061 cannot be met as literally written, and the reason matters

> *"Streamed responses begin within 3 seconds of request receipt."*

An M1 turn is **three sequential legs**: a plan call, a tool call, then the analysis call — and the
analysis call *is* the answer (ADR-015). The first token of the answer therefore cannot arrive before
plan + tool have completed, which is **~3.0–4.5 s** (derived, not measured — T40 fixes that). So:

* If "streamed response" means **the answer's first token**, NFR-061 is **unmeetable** by any transport,
  and no amount of streaming work will meet it. It is a requirement written against a one-LLM-call
  mental model of a turn that has two.
* If it means **the first frame of any kind**, it is met at ~0.1 s, trivially, and measures nothing.

**A single number that is either impossible or meaningless depending on interpretation is a defect, not
a target.** M2§11.2 replaces it with two requirements that measure two different things.

### 1.3 Two of M2's four rows are a different subsystem, and I am not building them here

FR-023 (multi-turn context) and FR-025 (conversation list and history) are a **read surface and a
prompt change**. They share no code with streaming, they carry their own risk — FR-023 changes what
goes into the plan prompt, which is the input to the five-layer validation ET-7 grades — and they can
ship independently in either order.

**Recommendation: M2 = streaming + cancellation. FR-023 and FR-025 become M2b.** Both are scoped in
M2§10 so nothing is lost, and M2b is a small milestone. The owner should confirm, because it is a
scope decision and not mine.

**And one finding he should have before deciding.** FR-023 is not partially done; it is **not done at
all, and the code currently looks as if it were**. `api/routes/chat.py` calls
`read_recent_messages(...)`, emits `context_loaded` with the count — and then never passes the result
to `executor.run_turn(...)`. `core/orchestrator/turn.py:183` builds the plan prompt as
`messages = [ChatTurn(role="user", content=message)]`: **the current message only.** SUNIL therefore
has no memory of the previous turn in a conversation, while a trace line says *"loaded 4 prior
message(s)"*. The line is true and the impression it gives is false. That is a defect worth its own
task whichever milestone owns it (T48).

---

## 2. What M2 builds, in one paragraph

`POST /api/v1/chat` gains a **streaming representation, selected by content negotiation**. With
`Accept: application/x-ndjson` the response is a stream of newline-delimited JSON frames — stage
events, answer tokens, and a terminal frame carrying the same envelope the JSON response would have
had. With `Accept: application/json` (the default, and what every existing client and test sends) the
response is byte-for-byte what it is today. The Model Router gains `run_stream()`; the OpenAI and
Anthropic providers gain `generate_stream()`; **only the analysis call streams** — the plan call is
structured output and is consumed whole. A client disconnect cancels the turn cooperatively, which is
what finally makes `tasks.status = cancelled` real.

---

## 3. The transport — argued against the SRS, not around it

**Decision: NDJSON frames streamed from the chat POST itself, selected by `Accept`. ADR-027, which
supersedes ADR-009 and contradicts FR-024.**

### 3.1 The three candidates

| | **A — separate SSE channel** (ADR-009's design) | **B — stream from the POST** (chosen) | **C — WebSocket** (FR-024, R§24) |
|---|---|---|---|
| Connections per turn | 2 | **1** | 2 (POST + socket) or 1 if the turn moves onto the socket |
| Correlation machinery | `TraceBus`: replay buffer, ownership claim, TTL, POST/SSE race | **none — the stream *is* the work** | connection registry keyed by conversation |
| Cancellation signal | none (a dropped SSE tells you nothing about the POST) | **client disconnect, free** | needs an application-level cancel message |
| Auth | cookie on a GET; `request_id` squatting must be defended (T-06) | **the POST's existing session + `X-SUNIL-Client` + CORS preflight** | **CORS does not apply to WebSocket** — a hand-written `Origin` check becomes the only CSRF control |
| Existing tests | unaffected | **unaffected** — `Accept: application/json` is the default | unaffected |
| Client code | `EventSource`, ~30 lines | `fetch` + `getReader()` + line split, ~50 lines | a socket lifecycle: reconnect, backoff, resubscribe, heartbeat |

### 3.2 Why B, in the order the reasons actually matter

1. **The correlation problem disappears rather than being solved.** ADR-009's `TraceBus` — a bounded
   replay buffer, an ownership claim, a 5-minute TTL, and a documented race in which "whoever arrives
   first creates the channel" — exists *entirely* because the stream is a different connection from the
   work. Streaming from the POST deletes all of it. **T12 was never built** (verified: no
   `StreamingResponse`, no `TraceBus`, no event-stream route anywhere in `apps/api/sunil/`), so nothing
   is thrown away by superseding it — only a specification.
2. **Cancellation becomes real, and free.** `DC-7` and debt `D-4` have wanted cooperative server-side
   cancellation since M1. With the stream on the POST, a client abort *is* the signal — M2§6.
3. **No second authentication path.** The POST already carries the session cookie, `X-SUNIL-Client`
   (ADR-008's CSRF control) and a CORS preflight bound to `WEB_ORIGIN`. **A WebSocket has none of
   those**: browsers do not apply CORS to WebSocket handshakes, so `X-SUNIL-Client` cannot be sent and
   the `Origin` check must be written by hand and got right. Swapping three mechanisms that already
   work for one that must be written is not a step forward.
4. **Progress events arrive as a frame type, not a second feature.** ADR-009's twelve stage events
   become `{"type":"stage",…}` frames on the same stream. `SUNIL_PROGRESS_EVENTS` is retired.
5. **ADR-009 rejected exactly this option for exactly one reason, and that reason has expired.** Its
   words: *"Genuinely elegant: one connection, no correlation, no replay buffer, and client disconnect
   would give a real cancellation signal. Rejected because it changes the POST response from a JSON
   object to a stream, which invalidates the exit tests QA is writing from FR-020 right now and would
   need an SRS amendment three days out."* **Content negotiation answers that**: `Accept:
   application/json` returns today's envelope unchanged, so ET-1 … ET-12 keep passing untouched, and
   FR-020's "within the same request/response cycle" stays literally true.

### 3.3 Why not WebSocket, said to the SRS's face

FR-024 and R§24 both name WebSocket. Duplex earns its cost when the client sends **application
messages** mid-stream. M2 has exactly one client→server signal — *stop* — and HTTP already expresses it
as a disconnect. Building a socket to carry a message that TCP already carries is paying a connection
lifecycle, a reconnect policy, a resubscribe protocol and a bespoke CSRF control for nothing.

**R§24's `/ws/conversations/{id}` is not wrong forever.** It becomes right when SUNIL pushes
*unsolicited* events to an idle client — a scheduled task finishing (M10), an agent needing approval
(M5), another device's turn appearing in a shared conversation. **None of those exist yet.** Recorded
as deviation **V-10** so the next person to read R§24 finds the argument instead of re-deriving it.

### 3.4 Why NDJSON and not SSE framing

An `EventSource` cannot issue a POST, so the client hand-parses either way; given that, one JSON object
per line is simpler to produce and to parse than `event:`/`data:` framing, and the frames need a `type`
field regardless. `Content-Type: application/x-ndjson`, `X-Accel-Buffering: no`, `Cache-Control:
no-cache`, and a heartbeat frame — which, per M2§6.2, is **not cosmetic**.

---

## 4. The wire format

One JSON object per line, `\n`-terminated. Every frame has `type`. Unknown frame types **must be
ignored by the client**, which is what keeps this list additive.

```
{"type":"stage","stage":"message_received","offset_ms":12,"detail":{...}}
{"type":"stage","stage":"plan_created","offset_ms":2480,"detail":{"project_key":"easy_clean_workforce",...}}
{"type":"token","text":"The "}
{"type":"token","text":"workforce "}
{"type":"heartbeat","offset_ms":4000}
{"type":"done","outcome":"ok","request_id":"...","conversation_id":"...","message":{...},"task":{...},"failure":null,"trace":[...],"usage":{...}}
```

| Frame | When | Notes |
|---|---|---|
| `stage` | each of the twelve, once | Identical `stage`/`offset_ms`/`detail` to today's `trace[]` entries and to ADR-009's SSE payload. **The 12→4 phase map stays in `apps/web/src/lib/phases.ts`** — the API sends enums (§11.2) |
| `token` | during the **analysis** call only | `text` is a raw delta, never HTML. Concatenating every `token.text` in order **must** equal `done.message.content`, and that is an exit test (ET-21) |
| `heartbeat` | every 1 s while no other frame has been sent | **Load-bearing** — M2§6.2 |
| `done` | exactly once, last | Carries **the whole of today's `ChatResponse`**. A client that ignores every other frame and reads only `done` behaves exactly like today's client |
| `error` | instead of `done`, only for a failure that prevents an envelope being built | Transport-level only. A *turn* failure is still `done` with `outcome:"failed"` and a `failure.kind` — §11.3's four values are untouched |

**`done` carrying the full envelope is the load-bearing decision.** It means the streaming
representation is a strict superset of the JSON one: the tokens are an *early view* of a value the
final frame delivers authoritatively. If the client drops a token frame, misparses one, or the
connection stutters, the answer is still correct and complete. **Streaming is a projection, never the
source of truth** — the same property that made ADR-009 safe, kept for the same reason.

---

## 5. Where streaming plugs into the pipeline

### 5.1 Only the analysis call streams. ADR-028.

M1 has two logical LLM stages (ADR-015): **plan** and **analysis**.

* **The plan call must not stream.** It uses structured output — `response_format={"type":
  "json_schema", …, "strict": true}` on OpenAI, `output_config` on Anthropic — and its value is
  consumed by `plan_validator` as a *whole document*. A partial JSON plan cannot be validated, cannot
  be re-checked against the registry, and cannot become a `ValidatedPlan`. Streaming it would produce
  bytes nobody may act on, purely so that something is moving on the wire. **A plan that is 80 %
  arrived is not 80 % validated, and the entire ADR-004 argument is that only a fully validated plan
  reaches an executor.**
* **The analysis call streams.** It is free text, it is the user-facing answer, and it is the only
  place a token means anything to a reader.

The user-visible consequence is that **nothing is spoken or typed for the first ~3.0–4.5 s of a turn** —
the stage frames carry that window, exactly as the four-phase `WorkIndicator` does today. That is
honest and it is the shape of the pipeline, not a limitation of the transport.

### 5.2 The provider interface grows one method

```python
@dataclass(frozen=True)
class StreamDelta:
    text: str                       # the token delta; never None, may be ""

@dataclass(frozen=True)
class StreamResult:                 # what the iterator's .result() yields at the end
    text: str                       # the full accumulated text
    input_tokens: int; output_tokens: int
    provider: str; model: str
    stop_reason: str | None
    provider_request_id: str | None
    latency_ms: int

class LLMProvider(Protocol):
    name: str
    def capabilities(self, model: str) -> ModelCapabilities: ...
    async def generate(self, model: str, request: LLMRequest) -> LLMResponse: ...
    def generate_stream(self, model: str, request: LLMRequest) -> LLMStream: ...   # NEW
```

`LLMStream` is an async iterator of `StreamDelta` with a terminal `result()` — **not** a bare
`AsyncIterator[str]`, because token counts and `stop_reason` arrive *after* the last delta and the
caller needs both to write its `llm_calls` row. A bare iterator would force the router to reconstruct
usage by counting characters, which is wrong and would silently corrupt ET-9's cost arithmetic.

`generate_stream` is **not** `async def` — it returns the stream object synchronously and the awaiting
happens on iteration. That mirrors both vendors' own shapes (M2§9) and keeps `async with` usable.

### 5.3 `llm_calls`, the trace, and the twelve stages

**Unchanged, and deliberately so** — the same argument ADR-023 made for voice:

* **One `llm_calls` row per provider attempt**, written when the stream completes, carrying the full
  accumulated `response_text` and the usage from the stream's terminal payload. A stream that dies
  mid-flight writes a row with `error_kind` and whatever text arrived — a partial answer that cost real
  money is still a row.
* **Twelve stages, once each.** `llm_io` is emitted once per logical stage as today; `agent_result`
  fires when the analysis stream completes. Token frames are **not** stage events, exactly as
  `llm_calls` rows are not stage events.
* `TraceStage` is not extended. ET-6 is untouched.

---

## 6. Cancellation — the thing streaming makes real. ADR-029.

`ADR-010` made cancel client-side only in M1: the browser aborts and stops rendering; the server keeps
working and keeps spending. `DC-7` and debt `D-4` have owned the fix since. Streaming delivers it
almost for free.

### 6.1 The mechanism, verified against the installed stack

```
user clicks Cancel
  → AbortController aborts the fetch
  → TCP close → ASGI "http.disconnect"
  → Starlette's StreamingResponse cancels the streaming task
  → asyncio.CancelledError propagates into the turn
  → the provider stream is closed in a `finally`
  → tasks.status = "cancelled"; final_response emitted with outcome "cancelled"
```

**Verified by reading the installed packages, and the detail matters.** `starlette==1.6.0`'s
`StreamingResponse.__call__` branches on the ASGI `spec_version`:

* `spec_version >= (2,4)` → disconnect surfaces as `ClientDisconnect` raised from an `OSError` **on the
  next send**;
* `spec_version < (2,4)` → a `listen_for_disconnect(receive)` task runs **concurrently** in a collapsing
  task group and cancels the stream immediately.

**The pinned `uvicorn==0.52.3` declares `spec_version: "2.3"`** (`h11_impl.py:207`,
`httptools_impl.py:228`), so SUNIL is on the *immediate* path today. **Recorded as a version-dependent
behaviour (debt D-19):** upgrading uvicorn to something declaring 2.4+ silently changes detection from
"immediate" to "on next send", and the only thing that keeps cancellation prompt in that world is the
heartbeat.

### 6.2 Which is why the heartbeat is not cosmetic

A 1-second heartbeat frame means there is always a send attempt pending within a second, so a
disconnect is noticed within a second **regardless of which Starlette branch is active**. It is the
difference between cancel meaning "stop within a second" and "stop whenever the model next produces
something", which during a 4-second plan call is not cancelling at all.

### 6.3 What `cancelled` costs the schema

`TaskStatus` gains `CANCELLED` — verified absent today (`PENDING · IN_PROGRESS · COMPLETED · FAILED`),
and it is enforced by a CHECK constraint, so this is **migration `0002`**.

**⚠️ Cross-milestone consequence, caught here rather than at merge: M9's migration renumbers.** The M9
plan was written when M9 was next and claimed `0002_voice`. M2 ships first, so **M2 takes `0002` and
M9 becomes `0003`**, and `main.py`'s `EXPECTED_ALEMBIC_HEAD` moves twice. `M9_BUILD_PLAN.md` T27 must be
read with that substitution.

`ChatResponse.outcome` gains `"cancelled"` alongside `"ok"`/`"failed"`. That **is** a change to the
frozen §6 contract and it is argued rather than slipped in: the alternative is reporting a cancelled
turn as `failed`, which puts a user's deliberate action in the same bucket as a provider outage and
makes the `tasks` table lie about why work stopped. The four `failure.kind` values are untouched;
`failure` is `null` on a cancelled turn.

---

## 7. The trust-boundary walk — one real streaming request at real addresses

My standing rule (L-001): no architecture is issued until one real *mutating* request has been walked
across every boundary at real addresses and ports. Two findings, 🔎.

**Addresses:** browser `http://localhost:3000` (`WEB_ORIGIN`), API `http://localhost:8000`, OpenAI
`https://api.openai.com/v1`.

1. `fetch("http://localhost:8000/api/v1/chat", {method:"POST", credentials:"include", signal,
   headers:{"Content-Type":"application/json", "Accept":"application/x-ndjson",
   "X-SUNIL-Client":"web", "X-Request-Id":<uuid4>}, body:…})`
2. 🔎 **CORS: `Accept` is a safelisted request header, so it adds no preflight requirement — but the
   preflight already happens** because of `Content-Type: application/json` and the two custom headers,
   and `main.py`'s `allow_headers` already lists all three. **No CORS change is needed.** Checked
   against the live middleware config rather than assumed.
3. 🔎 **`BaseHTTPMiddleware` and streaming — the finding that would have cost a day.**
   `RequestContextMiddleware` extends `BaseHTTPMiddleware`, which wraps the downstream response and
   re-emits its body through an internal queue. It does **not** buffer the whole body, so streaming
   works — but the response is copied frame-by-frame through an anyio memory object stream, and the
   `structlog.contextvars.bound_contextvars(...)` block in `dispatch()` **exits when `call_next`
   returns, which is before the body has finished streaming.** Log lines emitted by the generator after
   that point therefore lose their `request_id`. Fix, specified rather than discovered: the streaming
   generator binds `request_id` itself for its own duration. Cheap, and invisible until someone greps
   logs for a slow turn's tail and finds nothing.
4. `require_owner_session` → 401. `require_client_header` → 403. Unchanged.
5. Content negotiation: `Accept` contains `application/x-ndjson` → stream; otherwise → today's envelope.
   An unparseable or absent `Accept` → JSON, because the safe default is the behaviour that already
   exists.
6. `StreamingResponse(media_type="application/x-ndjson")`, `X-Accel-Buffering: no`,
   `Cache-Control: no-cache`.
7. The turn runs as today until the analysis call, which now uses `run_stream()`. Deltas are yielded as
   `token` frames; the twelve stages continue to be emitted and are relayed as `stage` frames.
8. On completion the `done` frame carries the full envelope, built by the same code that builds today's
   JSON body — **one builder, two representations**, so they cannot drift.
9. On abort: §6.1's chain. `tasks.status = "cancelled"`, `final_response` emitted with
   `outcome:"cancelled"`, the provider stream closed in a `finally`, and the `llm_calls` row written
   with the partial text and its real usage.

---

## 8. Latency — what M2 actually changes

**M2 changes perceived latency and nothing else. Total turn time is unchanged.**

| Measure | Today | With M2 |
|---|---|---|
| First frame of any kind | — (nothing until the response) | **~0.1 s** (the `message_received` stage frame) |
| First **token of the answer** | 5.8 s (the whole response at once) | **~3.0–4.5 s** — DERIVED, not measured; **T40 measures it first** |
| Whole answer complete | 5.8 s | **5.8 s** — unchanged |
| Cancel takes effect on the server | never (ADR-010) | **≤ ~1 s** (heartbeat-bounded) |

**The single most valuable measurement in this milestone is T40**, and it is deliberately the *first*
task, not a verification at the end. The 5.8 s turn has never been split into plan / tool / analysis.
Every latency claim in M2 and M9 rests on that split, and designing streaming without it means aiming
at a leg whose size nobody knows. If the analysis call turns out to be 1 s of a 5.8 s turn, streaming
it is close to pointless and the owner should hear that before eight more tasks are built —
**T40 is therefore a gate, not a chore.**

---

## 9. SDK facts, verified against the installed packages

Executed against `apps/api/.venv`, not read from documentation.

**OpenAI (`openai==3.1.0`) — the live hot path:**

* `chat.completions.create(..., stream=True)` returns `AsyncStream[ChatCompletionChunk]`.
  `AsyncCompletions.create` **fails `inspect.iscoroutinefunction`** (the `@required_args` wrapper, the
  same trap M9 recorded for `transcriptions.create`) while still returning an awaitable — so
  `stream = await client.chat.completions.create(...)`, then `async for chunk in stream`.
* ⚠️ **`AsyncStream` has `close()`, not `aclose()`** — and `close` **is** a coroutine function
  (verified). It also implements `__aenter__`/`__aexit__`, so **`async with` is the correct shape** and
  guarantees the socket is released when a turn is cancelled mid-stream. An engineer writing
  `await stream.aclose()` gets `AttributeError` at the worst moment.
* ⚠️ **Usage is opt-in and silently absent otherwise.** `stream_options` accepts
  `{"include_usage": bool, "include_obfuscation": bool}` (verified keys). **Without
  `stream_options={"include_usage": True}` the chunks carry no token counts**, `llm_calls.input_tokens`
  / `output_tokens` become zero, and **ET-9's cost arithmetic silently under-reports every streamed
  turn.** This is the highest-consequence line in the milestone and it is one keyword argument.
* `ChatCompletionChunk` fields: `id, choices, created, model, object, moderation, service_tier,
  system_fingerprint, usage`. `usage` is populated **only on the final chunk**, and that chunk normally
  has an empty `choices` list — so a reader that assumes every chunk has a delta will `IndexError` on
  the last one.
* `ChoiceDelta` fields: `content, function_call, refusal, role, tool_calls`. **`content` may be
  `None`** on role/refusal chunks; concatenating without a `None` guard raises `TypeError`.

**Anthropic (`anthropic==0.122.0`) — built, tested, one config line away:**

* `AsyncMessages.stream` exists and is **not** a coroutine function — it returns an
  `AsyncMessageStreamManager`, so the shape is `async with client.messages.stream(...) as stream:`,
  **different from OpenAI's `await create(stream=True)`**. Two vendors, two shapes; the `LLMStream`
  wrapper in `providers/base.py` is what stops that difference reaching the router.
* `AsyncMessages.create` also accepts `stream=True` for the lower-level path; the adapter uses
  `.stream()` because it accumulates usage without hand-rolling it.

---

## 10. What M2 does not deliver

| Not in M2 | Where |
|---|---|
| A faster turn | Nowhere. M2 changes perception; M2§8 |
| Streaming of the **plan** call | Never — ADR-028. A partial plan is not a validated plan |
| **FR-023** multi-turn context | **M2b (T48).** And it is *not* partially done — prior messages are loaded, counted, traced, and then discarded (M2§1.3). The trace line is true; the impression is false |
| **FR-025** conversation list and history | **M2b** |
| WebSocket channels (R§24 `/ws/…`) | When unsolicited server-push exists — M5 approvals, M10 schedules. Deviation **V-10** |
| Concurrent turns in one conversation | Not a V1 requirement; one turn at a time, as M1 |
| Resume of a dropped stream | Rejected: `done` carries the whole envelope, so a client that reconnects can simply re-read state. A resume token would be machinery for a case a page refresh already handles |
| Token-level cost attribution *during* a turn | `llm_calls` is written when the stream completes. A live running total would need a second write path for a number that is final one second later |
| Server-side spend cap | Still **DC-5, M3**. Cancellation reduces waste; it is not a budget control |

---

## 11. The requirement set FR-024 must become

Normative for M2, in `REQUIREMENTS_V1.md`'s own format, ready to lift into §4.2.

### 11.1 Functional

| ID | Pri | M | Statement | Ref |
|---|---|---|---|---|
| FR-024 | MUST | M2 | SUNIL's answer is delivered to the chat UI incrementally as it is generated, so the owner sees text appear before the turn completes. **The transport is an architectural decision, not a requirement** (ADR-027). | R§14 Epic 2 |
| FR-024a | MUST | M2 | The streaming representation is selected by content negotiation. A client that does not request it receives the existing single-payload response unchanged. | ADR-027 |
| FR-024b | MUST | M2 | The final frame of a stream carries the complete response envelope — outcome, message, task, failure, trace and usage — so a client that reads only that frame behaves identically to a non-streaming client. | ADR-027 |
| FR-024c | MUST | M2 | Concatenating the incremental text fragments in order yields exactly the final message content. | ET-21 |
| FR-024d | MUST | M2 | Progress stages are delivered on the same stream as the answer text; there is no second channel and no second endpoint. | ADR-027 |
| FR-024e | MUST | M2 | Only the user-facing answer is streamed. Any model output used as a system decision is consumed whole and validated before use. | ADR-028, ADR-004 |
| FR-027 | MUST | M2 | The owner can cancel an in-flight turn, and the server stops work: no further provider calls are started, the in-flight one is closed, and the turn reaches a terminal recorded state. | ADR-029, DC-7, D-4 |
| FR-028 | MUST | M2 | A cancelled turn is recorded as `cancelled`, distinctly from `failed`, on both the task and the response. | ADR-029 |
| FR-029 | MUST | M2 | A turn cancelled mid-generation still records the provider attempt it consumed, with its real token usage and cost. | NFR-030 |
| FR-030 | SHOULD | M2 | A stream that produces no other frame emits a keep-alive at least once per second. | ADR-029 §6.2 |

### 11.2 Non-functional — NFR-061 replaced by two measurable requirements

| ID | Pri | M | Statement | Verification |
|---|---|---|---|---|
| ~~NFR-061~~ | — | — | **WITHDRAWN.** "Streamed responses begin within 3 seconds of request receipt" is unmeetable if it means the answer's first token (the answer is the third of three sequential legs) and meaningless if it means any frame. M2§1.2 | — |
| NFR-061a | MUST | M2 | The first frame of a streamed turn reaches the client within **500 ms** of request receipt. | 10 timed runs; report median and max |
| NFR-061b | SHOULD | M2 | The first fragment of **answer text** reaches the client within **5 s** at the median. **This is a claim about the pipeline, not the transport** — it cannot be improved by streaming work, only by changing what happens before the answer exists. | 10 timed runs, **reporting the plan / tool / analysis split separately** — T40 |
| NFR-063 | MUST | M2 | A cancelled turn stops server-side work within **1.5 s** of the client aborting. | Fault-injection: abort mid-turn, assert no further `llm_calls` rows and a terminal `cancelled` task |

### 11.3 Exit tests

| ID | Test |
|---|---|
| ET-19 | With `Accept: application/json`, `POST /api/v1/chat` returns byte-identical behaviour to M1 — ET-1 … ET-12 pass unmodified against the streaming build. |
| ET-20 | With `Accept: application/x-ndjson`, a turn yields ≥1 `stage` frame, ≥2 `token` frames, and exactly one terminal `done` frame, in that order. |
| ET-21 | Concatenating every `token.text` in order equals `done.message.content` exactly. |
| ET-22 | The twelve stages appear on the stream **and** in `audit_events`, all twelve, in order, once each — ET-6 holds for a streamed turn. |
| ET-23 | A client abort mid-stream produces `tasks.status = "cancelled"`, a `final_response` audit row, no further `llm_calls` rows, and no tool call. |
| ET-24 | A turn cancelled during the analysis call writes an `llm_calls` row with non-zero `input_tokens` and a real `cost_micro_usd` — a partial answer that cost money is still recorded. |
| ET-25 | A streamed turn's `usage.input_tokens`/`output_tokens` are non-zero and equal the non-streamed turn's for the same fixture — the `stream_options={"include_usage": True}` regression test. |

### 11.4 SRS edits this implies

* §4.2 gains FR-024a–e, FR-027 … FR-030; FR-024 is reworded to drop "over WebSocket".
* §5.6 withdraws NFR-061 and adds NFR-061a/b and NFR-063.
* **Total functional requirements: 61 → 70** (before M9's separate +14).
* FR-023 and FR-025 are re-tagged **M2b**, and FR-023 gains a note that it is unimplemented rather than
  partial.
* BL-001 splits: streaming + cancellation (M2) and history + multi-turn (M2b).

---

## 12. Security — additions to the threat model (§13)

| ID | Threat | Control | Status |
|---|---|---|---|
| T-44 | **A long-lived streaming request holds a DB session and a provider socket**, so a handful of abandoned turns exhaust the pool | The turn's session is request-scoped and released in a `finally`; the provider stream is closed with `async with`; disconnect cancels within ~1 s (heartbeat-bounded). One user, one concurrent turn | **Mitigated for M1/M2's scope**, and the scope is the reason — no connection cap exists. DC-19's rate-limit gap covers it from M11 |
| T-45 | **Partial answers leak through a failed turn.** A stream that dies after 200 tokens has shown the owner text no `messages` row will hold | Deliberate: `done`/`error` states it plainly and the client marks the message incomplete. The partial text **is** persisted on the `llm_calls` row, so the trace is not silently short | **Accepted, and made visible** rather than hidden |
| T-46 | **Token frames bypass the redaction hook.** §8.3 scrubs `llm_calls.response_*` *before insert*; a token frame reaches the browser before any insert happens | Secrets are never in a prompt (§9.1), so a model reproducing one would have had to be told it. **But the guarantee is now weaker than "redaction covers the response":** live text is unredacted by construction. **Decision: `scrub()` runs on each delta before it is framed.** Per-frame cost is a dictionary walk over a ~20-character string | **Mitigated by moving the hook**, and the weakening is recorded because the honest default would have been to miss it |
| T-47 | **Cancellation as a denial-of-wallet amplifier** — repeated start/cancel could burn plan-call spend with nothing to show | Every attempt is costed into `llm_calls` regardless, so it is visible. No cap exists — **DC-5, M3**, unchanged | **Accepted, visible, uncapped** |
| T-48 | **NDJSON frame injection** — untrusted tool content reaching a `token` frame and breaking framing | Frames are built with `json.dumps`, never string concatenation; a newline inside a string is escaped by the serialiser. The client parses each line with `JSON.parse` and **ignores unknown `type` values** | **Mitigated** |

**T-46 is the one worth the owner's attention**: it is a control that M1 has and M2 would have quietly
lost, and it was found by asking what the redaction hook covers rather than by assuming it still did.

---

## 13. Dependencies

**M2 adds none.** `StreamingResponse` is Starlette's; NDJSON is `json.dumps` plus `"\n"`; both SDKs'
streaming APIs are in the pinned versions. `sse-starlette` remains rejected (§14.3) and is now doubly
unnecessary, since the format is not SSE.

---

## 14. Debt

| # | Debt | Owner |
|---|---|---|
| D-19 | **Cancellation promptness is uvicorn-version-dependent.** `uvicorn==0.52.3` declares ASGI `spec_version "2.3"`, so Starlette runs a concurrent disconnect listener; a version declaring 2.4+ switches to detect-on-next-send and the heartbeat becomes the only thing keeping cancel prompt. Pin-and-note, and re-test on upgrade | whoever upgrades uvicorn |
| D-20 | **`BaseHTTPMiddleware`'s contextvar scope ends before the body finishes streaming**, so late log lines lose `request_id` unless the generator re-binds it. Worked around in the generator; the underlying awkwardness stays | M11 |
| D-21 | Migration numbering moved: **M2 takes `0002`, M9 becomes `0003`.** `M9_BUILD_PLAN.md` T27 still says `0002_voice` and must be read with this substitution | M9's T27 |
| D-22 | `SUNIL_PROGRESS_EVENTS` is retired by ADR-027. The frontend's `openProgressEvents()` and its `useTurn` call site are dead code pointing at an endpoint that never existed and must be removed with T46, not left to rot | T46 |
