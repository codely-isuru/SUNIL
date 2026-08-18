# M2 — Streaming and cancellation: build plan (T40 … T51)

**Author:** Solution Architect, Minions Team 18 · **Date:** 2026-08-19
**Architecture:** [`docs/ARCHITECTURE_M2_STREAMING.md`](ARCHITECTURE_M2_STREAMING.md) — `M2§n` below.
**Decisions:** ADR-027 (supersedes ADR-009), ADR-028, ADR-029 (supersedes ADR-010 in part).
**Requirements of record:** `ARCHITECTURE_M2_STREAMING.md` §11 until the BA merges it into
`REQUIREMENTS_V1.md` §4.2 and §5.6.
**Git workflow (Delivery Manager's document, in force):** [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) —
one branch per task, `task/T<n>-<slug>`, cut from current `main`, never committed to `main`.
**Downstream:** [`docs/M9_BUILD_PLAN.md`](M9_BUILD_PLAN.md) — M9 builds on this and starts after it.

---

## 0. Read this before drawing a task

**M2 is the next build because the owner reversed the order on 2026-08-19.** M9 (voice) follows it, so
what M2 leaves behind is what M9's sentence chunker consumes. Getting `StreamDelta` right matters twice.

**Three rules M1 learned the hard way, unchanged:**

1. **Exclusive file ownership, and it means the whole file.** §1 assigns every file to exactly one
   task. Where two tasks need one file, they are separated **in time, not in space**.
2. **A branch is green against what it was cut from, not against what exists.** Three confirmed M1
   defects came from this. Every task **merges current `main` and re-runs the full suite before
   requesting review.**
3. **Verify SDK facts against the installed package.** It caught four defects in M1, four more in M9's
   design pass, and four in this one (M2§9) — including `stream_options={"include_usage": True}`,
   whose absence would have silently zeroed the cost of every streamed turn.

**Test-file basenames must be globally unique.** M1 lost a whole collection run to two
`test_capture.py` files in directories without `__init__.py`.

**⚠️ Migration numbering.** M2 takes **`0002`** (`TaskStatus.CANCELLED`). **M9's `0002_voice` becomes
`0003_voice`** — `M9_BUILD_PLAN.md` T27 still says `0002` and must be read with that substitution
(debt D-21).

---

## 1. File ownership map — every file, exactly one owner

| File | Owner |
|---|---|
| `apps/api/tests/integration/test_turn_leg_timings_live.py`, `docs/worklog/2026-08-2x-m2-leg-split.md` | **T40** |
| `apps/api/sunil/providers/base.py` | **T41** |
| `apps/api/sunil/providers/openai.py` | **T42** |
| `apps/api/sunil/providers/anthropic.py` | **T43** |
| `apps/api/sunil/core/routing/router.py` | **T44** |
| `apps/api/sunil/api/streaming.py` *(new — frame types + the NDJSON writer)* | **T45** |
| `apps/api/sunil/api/schemas.py` | **T45** |
| `apps/api/sunil/api/routes/chat.py` | **T46** |
| `apps/api/sunil/core/orchestrator/turn.py` | **T46** |
| `apps/api/sunil/api/middleware.py` | **T46** |
| `apps/api/sunil/settings.py` | **T46** (removes `sunil_progress_events`) |
| `apps/api/sunil/db/models.py`, `apps/api/migrations/versions/0002_cancelled.py`, `apps/api/sunil/main.py`, `apps/api/sunil/core/tasks/service.py` | **T47** |
| `apps/web/src/lib/api.ts`, `apps/web/src/lib/useTurn.ts`, `apps/web/src/lib/streamFrames.ts`, `apps/web/src/components/chat/{AssistantMessage.tsx,types.ts,index.ts}`, `apps/web/src/app/(chat)/page.tsx` | **T49** |
| `apps/api/tests/exit/test_et19_*.py` … `test_et25_*.py`, `apps/api/tests/exit/_stream_client.py` | **T50** |
| `apps/api/tests/security/test_stream_redaction.py`, `apps/api/tests/security/test_stream_framing.py` | **T51** |
| *(M2b, not built in M2)* `core/conversations/history.py`, `api/routes/conversations.py` | **T48** |

**Documents nobody on this milestone edits:** `docs/STATUS.md`, `docs/GIT_WORKFLOW.md`,
`docs/M9_BUILD_PLAN.md`.

---

## 2. Dependency graph and the critical path

```
T40 (MEASURE — a gate, not a chore)
 └─► T41 ─┬─► T42 ─┐
          └─► T43 ─┴─► T44 ─► T45 ─► T46 ─┬─► T49 ─► T50
                                          └─► T47 ──┘
                                    T51 depends on T46 + T49
T48 is M2b and is not built in M2
```

**Critical path: T40 → T41 → T42 → T44 → T45 → T46 → T49 → T50.**
T43 (Anthropic) runs beside T42 and is off the critical path — the hot path is OpenAI. T47 (the
`cancelled` state) runs beside the frontend work.

**T40 is a gate.** If it reports that the analysis call is a small fraction of the 5.8 s turn, the
value of streaming it drops sharply and the owner should hear that before eight more tasks are built.
No task after T40 starts until its number is on the table.

---

## 3. The measurement that comes first

### T40 — Split the 5.8 s turn into plan / tool / analysis

**Deps:** none. **Requires the owner's real key** — `@pytest.mark.live`, deselected in CI via
`-m "not live"` (there is no `tests/live/` directory in this repo; live tests sit beside their peers and
are selected by marker, as `tests/security/test_live_credential_scope.py` already does).
**Owns:** `apps/api/tests/integration/test_turn_leg_timings_live.py`,
`docs/worklog/2026-08-2x-m2-leg-split.md`.

**Build:** 10 real turns against the live path. For each, read `audit_events` and `llm_calls` and
compute, **per leg**: `message_received → plan_created` (the plan call), `plan_created → tool_result`
(the tool call), `tool_result → agent_result` (the analysis call), and the residual overhead. Report
**median and maximum per leg** — never a single figure, which is §5.2's standing rule ("median and max
of N observed turns … not arithmetic theatre").

**Then edit two documents in place** and remove their DERIVED labels:
`ARCHITECTURE_M2_STREAMING.md` §8 and `ARCHITECTURE_M9_VOICE.md` §9.1 leg 6a. Close debt D-16's first
half.

**Why this is first and not last.** Every latency claim in M2 and M9 rests on this split and **the
split has never been measured** — the 5.8 s figure is a total. Designing streaming without it means
aiming at a leg whose size nobody knows.
**Report to the DM before T41 starts.** If the analysis call is a small share of the turn, say so
plainly: streaming it is still correct (the user sees the answer forming) but the *perceived* win is
smaller than M2§8 claims, and that is the owner's decision to hear, not this plan's to bury.
**Satisfies:** NFR-061b's verification method. **Exit tests:** none — this is measurement.

---

## 4. Backend provider lane

### T41 — The streaming seam in the provider protocol

**Deps:** T40. **On the critical path.**
**Owns:** `apps/api/sunil/providers/base.py`.

**Build:** `StreamDelta`, `StreamResult` and `LLMStream` exactly as `ARCHITECTURE_M2_STREAMING.md` §5.2
specifies, plus `generate_stream()` on the `LLMProvider` Protocol.

* `LLMStream` is an async iterator of `StreamDelta` **with a terminal `result() -> StreamResult`** —
  **not** a bare `AsyncIterator[str]`. Token counts and `stop_reason` arrive after the last delta, and
  a caller that has to count characters to estimate usage writes a wrong number into a column that
  reads as authoritative (ADR-028).
* `LLMStream` implements `__aenter__`/`__aexit__` so callers can guarantee socket cleanup with
  `async with` when a turn is cancelled mid-stream.
* `generate_stream` is **not** `async def` — it returns the stream object synchronously and awaiting
  happens on iteration, matching both installed SDKs' shapes.
* **No vendor import.** This file is the seam, not an adapter.

**Tests** (`tests/unit/providers/test_stream_protocol.py`): a fake stream yields deltas then a
`StreamResult` · `result()` before exhaustion raises a named error rather than returning zeros ·
`async with` closes the stream when the body raises · `StreamDelta.text` is never `None`.
**Interfaces produced:** `StreamDelta(text: str)`; `StreamResult(text, input_tokens, output_tokens,
provider, model, stop_reason, provider_request_id, latency_ms)`; `LLMStream` with
`__aiter__`/`__anext__`/`result()`/`__aenter__`/`__aexit__`; `LLMProvider.generate_stream(model, request) -> LLMStream`.
**Satisfies:** FR-024 (seam). **Exit tests:** foundations for ET-20, ET-25.

### T42 — OpenAI streaming (the hot path)

**Deps:** T41. **On the critical path.**
**Owns:** `apps/api/sunil/providers/openai.py`.

**Build:** `generate_stream()` on the existing adapter.

* `stream = await client.chat.completions.create(..., stream=True, stream_options={"include_usage": True})`.
  **⚠️ `stream_options={"include_usage": True}` is mandatory.** Verified against the installed
  `openai==3.1.0`: without it the chunks carry no usage, `input_tokens`/`output_tokens` land as zero,
  and **ET-9's cost arithmetic silently under-reports every streamed turn.** ET-25 exists for this one
  keyword argument.
* **`AsyncCompletions.create` fails `inspect.iscoroutinefunction`** (the `@required_args` wrapper — the
  same trap M9 recorded for `transcriptions.create`) while still returning an awaitable. Do not let a
  mock's autospec decide whether to await.
* **⚠️ `AsyncStream` has `close()`, not `aclose()`**, and `close` **is** a coroutine function. It also
  implements `__aenter__`/`__aexit__` — **use `async with`.** `await stream.aclose()` is an
  `AttributeError` at the worst possible moment.
* **⚠️ The final chunk carries `usage` and normally has an empty `choices` list.** A reader that does
  `chunk.choices[0]` unconditionally raises `IndexError` on the last chunk of every successful stream.
* **⚠️ `ChoiceDelta.content` may be `None`** on role/refusal chunks. Concatenating without a guard
  raises `TypeError`.
* Errors classified **by `status_code`** (A-16), never by class name — unchanged from `generate()`.
* `base_url` still passed explicitly from `Settings` (ADR-017).

**Tests** (`tests/unit/providers/test_openai_stream.py`), against a **loopback HTTP double** driven by
`OPENAI_BASE_URL` (ADR-017's transport seam — a protocol fake would only assert the fake): deltas are
yielded in order · the accumulated text equals the concatenation · **`stream_options` with
`include_usage: true` appears in the outbound request body** (assert on what the double received —
this is the regression test that matters) · a final chunk with empty `choices` and a `usage` payload is
handled without `IndexError` · a `None` `content` delta does not raise · `result()` carries non-zero
token counts · a 429 mid-stream → `ProviderTransientError` · cancelling the consumer closes the stream.
**Satisfies:** FR-024, FR-029. **Exit tests:** ET-20, ET-21, ET-25.

### T43 — Anthropic streaming (off the critical path)

**Deps:** T41. **Parallel with T42.**
**Owns:** `apps/api/sunil/providers/anthropic.py`.

**Build:** `generate_stream()` using **`async with client.messages.stream(...) as stream:`**.

* ⚠️ **A different shape from OpenAI's, verified:** `AsyncMessages.stream` is **not** a coroutine
  function — it returns an `AsyncMessageStreamManager`, so it is `async with`, not `await`. Do not
  copy T42's call shape.
* `.stream()` is preferred over `create(stream=True)` because it accumulates usage without hand-rolling
  it.
* The whole point of `LLMStream` is that this difference stops here: the router sees one type.

**Tests** (`tests/unit/providers/test_anthropic_stream.py`), against a loopback double driven by
`ANTHROPIC_BASE_URL`: same assertions as T42 where they apply · `result()` carries non-zero token
counts · the adapter is never `await`ed as if it were OpenAI's.
**Satisfies:** FR-024 (second provider — ADR-003 §4.6's claim, tested again).

### T44 — `ModelRouter.run_stream()`

**Deps:** T41, T42. **On the critical path.**
**Owns:** `apps/api/sunil/core/routing/router.py`.

**Build:** `run_stream(capability, request, ...)` mirroring `run()`'s policy exactly:

* capability lookup, **turn-deadline check before starting any attempt** (§5.3 — an attempt whose
  timeout exceeds the remaining budget is not started), bounded retry with jitter;
* **one `llm_calls` row per provider attempt**, written **when the stream completes**, carrying the
  full accumulated `response_text` and the real usage from `StreamResult`;
* a stream that dies mid-flight still writes its row, with `error_kind` and whatever text arrived —
  **a partial answer that cost money is still a row** (ET-24);
* **the router still emits no trace stages** (A-17) — its callers do. `run_stream()` returns the
  attempt count exactly as `run()` does;
* **retry only before the first delta.** Once a delta has been yielded to the caller, a retry would
  re-emit text the user has already seen. On a mid-stream failure the router closes the stream and
  raises; it does not restart. **State this in the docstring** — it is the non-obvious half of the
  policy.

**Tests** (`tests/unit/routing/test_router_stream.py`): one row per attempt · a transient failure
**before** the first delta retries; **after** the first delta it does not · a completed stream's row
carries the full text and non-zero usage · a killed stream's row carries `error_kind` and the partial
text · the deadline check refuses an attempt that cannot finish · **no stage is emitted from inside the
router**.
**Satisfies:** FR-024, FR-029, NFR-030, NFR-070. **Exit tests:** ET-24, ET-25.

---

## 5. Backend API lane

### T45 — Frame types, the NDJSON writer, and the schema additions

**Deps:** T44. **On the critical path.**
**Owns:** `apps/api/sunil/api/streaming.py` *(new)*, `apps/api/sunil/api/schemas.py`.

**Build:**
* Frame models exactly per `ARCHITECTURE_M2_STREAMING.md` §4: `StageFrame`, `TokenFrame`,
  `HeartbeatFrame`, `DoneFrame`, `ErrorFrame`, each with a literal `type`.
* `write_frame(frame) -> bytes` — `json.dumps(...) + "\n"`. **Never string concatenation**: a newline
  inside a string must be escaped by the serialiser, which is what makes frame injection impossible
  (T-48).
* `negotiate(accept: str | None) -> Literal["json","ndjson"]`. Absent, empty or unparseable `Accept` →
  **`json`**, because the safe default is the behaviour that already exists.
* **One envelope builder, two representations.** The function that builds today's `ChatResponse` is
  what fills `DoneFrame`; it is not duplicated. A test asserts a streamed and a non-streamed turn on
  the same fixture produce identical envelopes.
* `ChatResponse.outcome` gains `"cancelled"` (ADR-029). The four `failure.kind` values are untouched
  and `failure` is `None` on a cancelled turn.

**Tests** (`tests/unit/api_routes/test_stream_frames.py`): every frame round-trips through
`json.loads` · a `token.text` containing `"\n"`, `"}"` and `'"'` produces exactly one output line that
parses back to the original string · `negotiate` returns `json` for `None`, `""`, `"*/*"`,
`"application/json"` and garbage, and `ndjson` only for an `Accept` containing `application/x-ndjson` ·
the envelope builder is called once and produces the same object both ways.
**Interfaces produced:** `write_frame(frame: Frame) -> bytes`; `negotiate(accept) -> Literal["json","ndjson"]`;
`build_envelope(...) -> ChatResponse` (the single builder both representations use).
**Satisfies:** FR-024a, FR-024b, FR-024d. **Exit tests:** ET-19, ET-20.

### T46 — The streaming chat route, and the turn that feeds it

**Deps:** T45. **On the critical path.**
**Owns:** `apps/api/sunil/api/routes/chat.py`, `apps/api/sunil/core/orchestrator/turn.py`,
`apps/api/sunil/api/middleware.py`, `apps/api/sunil/settings.py`.

**Build:**
* Content negotiation in the route: `json` → today's code path **entirely unchanged**; `ndjson` →
  `StreamingResponse(media_type="application/x-ndjson")` with `X-Accel-Buffering: no` and
  `Cache-Control: no-cache`.
* `LiveTurnExecutor` gains a streaming path: the analysis call uses `run_stream()`, yielding
  `StreamDelta`s to the route, which frames them as `token`. **The plan call is unchanged and does not
  stream** (ADR-028).
* Stage emissions are relayed as `stage` frames. **The twelve stages, once each, are unchanged** —
  `TraceStage` gains no member and ET-6 is untouched.
* **A `heartbeat` frame every 1 s while no other frame has been sent.** It is not decoration: it is
  what bounds cancellation latency (ADR-029 §2).
* **⚠️ Re-bind `request_id` inside the streaming generator.** `RequestContextMiddleware` extends
  `BaseHTTPMiddleware`, whose `bound_contextvars(...)` block exits when `call_next` returns — **before
  the body has finished streaming** — so log lines emitted late in a stream lose `request_id` unless
  the generator binds it itself. Debt D-20; this is the workaround, specified rather than discovered.
* **`scrub()` runs on each delta before it is framed** (T-46). §8.3's hook runs before *insert*, and a
  token frame reaches the browser before any insert happens — so without this, live text is unredacted
  by construction. Per-frame cost is a dict walk over ~20 characters.
* **Delete `sunil_progress_events` from `settings.py`.** ADR-027 retires it; T12 was never built and
  nothing reads it.

**Tests** (`tests/unit/api_routes/test_chat_streaming.py`): `Accept: application/json` produces a
response byte-identical to the current implementation on the same fixture · `Accept:
application/x-ndjson` produces stage frames, then token frames, then exactly one `done` · every line
parses as JSON · `done` carries the full envelope · a heartbeat appears within 1.2 s of a quiet period ·
a registered secret placed in a fake model's output **does not appear in any token frame** · late log
lines carry `request_id`.
**Satisfies:** FR-024, FR-024a–e, FR-030. **Exit tests:** ET-19, ET-20, ET-21, ET-22.

### T47 — `cancelled` as a terminal state, and migration `0002`

**Deps:** T45. **Parallel with T46's later half.**
**Owns:** `apps/api/sunil/db/models.py`, `apps/api/migrations/versions/0002_cancelled.py`,
`apps/api/sunil/main.py`, `apps/api/sunil/core/tasks/service.py`.

**Build:**
* `TaskStatus.CANCELLED` — verified absent today (`PENDING · IN_PROGRESS · COMPLETED · FAILED`) and
  enforced by a CHECK constraint, so it is a migration.
* `0002_cancelled`: widen the `tasks.status` CHECK. Downgrade narrows it, **and must first fail loudly
  if any `cancelled` row exists** rather than silently corrupting one.
* `main.py`: `EXPECTED_ALEMBIC_HEAD = "0002"`. **Nothing else in this file.**
* `tasks/service.py`: a legal transition into `cancelled` from `pending` and `in_progress`, and from
  nowhere else — a completed turn cannot be retro-cancelled.
* Cancellation handling in the turn's `finally`: close the provider stream, write the terminal task
  state, emit `final_response` with `outcome:"cancelled"`. **No rollback** — a cancelled turn is a
  recorded turn (ADR-029).

**Tests** (`tests/unit/tasks/test_cancelled_transitions.py`, `tests/unit/test_migration_0002.py`):
`cancelled` is reachable from `pending` and `in_progress` and from nothing else · `0002` upgrades and
downgrades cleanly on SQLite · downgrade with a `cancelled` row present **raises** · `final_response`
is still emitted on a cancelled turn (the ET-8 property, extended).
**Satisfies:** FR-027, FR-028. **Exit tests:** ET-23, ET-24.
**⚠️ Note for M9:** this takes `0002`. M9's voice migration is **`0003`** (debt D-21).

---

## 6. Frontend lane

The frontend still has **no test runner** (M1 debt, deferred to M11). T49 ships verified by review plus
T50's exit tests. It may not add a test library on its own authority.

### T49 — Consume the stream, render tokens, mean the cancel

**Deps:** T46, T47. **On the critical path.**
**Owns:** `apps/web/src/lib/{api.ts,useTurn.ts,streamFrames.ts}`,
`apps/web/src/components/chat/{AssistantMessage.tsx,types.ts,index.ts}`,
`apps/web/src/app/(chat)/page.tsx`.

**Build:**
* `streamFrames.ts`: `fetch` with `Accept: application/x-ndjson`, then `res.body.getReader()`, a
  `TextDecoder`, and a **line buffer that carries a partial trailing line between chunks** — a network
  chunk boundary lands mid-line often, and a naive `split("\n")` per chunk drops or corrupts a frame.
  Unknown `type` values are **ignored**, which is what keeps the frame list additive.
* `useTurn`: render `token.text` into the in-flight assistant message; drive the four phases from
  `stage` frames instead of the timed fallback; on `done`, **replace the accumulated text with
  `done.message.content`** — the authoritative value — so a dropped frame self-heals.
* **Delete `openProgressEvents()` and its call site** (debt D-22). It points at an endpoint that never
  existed.
* Render the new `cancelled` outcome. `cancelTurn()` already aborts; the change is that the abort now
  means something server-side.
* `AssistantMessage` renders incrementally. **Markdown must not be re-parsed per token** — parse the
  accumulated text on a frame boundary at most every ~100 ms, or a long answer re-parses hundreds of
  times and the tab stutters.
* **Reduced motion:** incremental text is not motion and is unaffected. **Screen readers:** the
  streaming message is **not** `aria-live` — announcing every token is unusable; the completion is
  announced once, matching `M1_CHAT_SPEC.md` §5.3's "4 updates max per turn" discipline.

**Satisfies:** FR-024, FR-027, FR-028. **Verified by:** review + ET-19 … ET-23.

---

## 7. QA and Security lanes

### T50 — Exit tests ET-19 … ET-25 (QA)

**Deps:** T46, T47, T49.
**Owns:** `apps/api/tests/exit/_stream_client.py`,
`apps/api/tests/exit/test_et19_json_accept_unchanged.py`,
`test_et20_ndjson_frame_sequence.py`, `test_et21_token_concat_equals_message.py`,
`test_et22_twelve_stages_on_stream.py`, `test_et23_abort_cancels_turn.py`,
`test_et24_cancelled_turn_records_cost.py`, `test_et25_streamed_usage_is_recorded.py`.

**Build:** `_stream_client.py` reads an NDJSON response and returns the parsed frames, with a
**deliberately adversarial chunker** in its fixture — it must feed the parser bytes split mid-line and
mid-multibyte-character, because that is what a real network does and it is the single most likely
place a hand-written frame reader is wrong.

**ET-19 is the load-bearing one:** run the entire existing exit suite (ET-1 … ET-12) unmodified against
the streaming build with the default `Accept`. If any of them needs a change, ADR-027's central claim —
that content negotiation preserves the frozen contract — is false, and that is a design defect to
escalate, not a test to adjust.

**ET-25 exists for one keyword argument.** A streamed turn's `usage` must be non-zero and equal the
non-streamed turn's for the same fixture. Delete `stream_options={"include_usage": True}` and this test
must go red; a QA engineer should verify that by deleting it once.
**Satisfies:** the M2 exit criteria.

### T51 — Redaction on the live path, and frame framing (SEC)

**Deps:** T46, T49.
**Owns:** `apps/api/tests/security/test_stream_redaction.py`,
`apps/api/tests/security/test_stream_framing.py`.

**Build:**
* **T-46, the one that matters.** §8.3's redaction hook runs on `llm_calls.response_*` **before
  insert** — and a token frame reaches the browser before any insert happens. Assert that a registered
  secret value emitted by a fake provider **never appears in any token frame**, and that it is scrubbed
  in the persisted row too. This is a control M1 had and M2 could have quietly lost.
* **T-48.** A `token.text` containing `"\n"`, `"\r\n"`, `"}"`, a lone `"` and a ` ` produces
  exactly one parseable line whose decoded value equals the original.
* A frame with an unknown `type` is ignored by the client parser rather than throwing.
**Satisfies:** NFR-001/005 on the streaming path. **Exit tests:** supports ET-21.

---

## 8. M2b — scoped, not built

### T48 — Multi-turn context (FR-023) and conversation history (FR-025)

**Not part of M2.** Scoped here so nothing is lost and so the DM can schedule it.

**The finding that makes FR-023 urgent, and it is a defect, not a gap.**
`api/routes/chat.py` calls `read_recent_messages(...)`, emits `context_loaded` with the count — and
**never passes the result to `executor.run_turn(...)`**. `core/orchestrator/turn.py:183` builds the plan
prompt as `messages = [ChatTurn(role="user", content=message)]`: **the current message only.** SUNIL has
no memory of the previous turn, while the trace says *"loaded 4 prior message(s)"*. The line is true and
the impression it gives is false. Whichever milestone owns this, that sentence should be in its brief.

**Why it is not folded into M2:** it changes the plan prompt, which is the input to the five-layer
validation ET-7 grades, and it raises per-turn token cost. That is its own blast radius and its own
review, and it shares no code with streaming.

**Scope when built:** pass `recent_messages` into `run_turn`; convert to `ChatTurn`s with a token
budget; `GET /api/v1/conversations` and `GET /api/v1/conversations/{id}/messages`; re-run ET-2 and ET-7
against a multi-turn prompt.

---

## 9. Exit-test coverage map

| Exit test | Proved by |
|---|---|
| ET-19 — `Accept: application/json` unchanged; ET-1…ET-12 pass unmodified | T45, T46, T50 |
| ET-20 — frame sequence: stage → token → one `done` | T45, T46, T50 |
| ET-21 — token concatenation equals `done.message.content` | T42, T46, T50, T51 |
| ET-22 — twelve stages on the stream **and** in `audit_events` | T46, T50 |
| ET-23 — abort cancels the turn server-side | T46, T47, T49, T50 |
| ET-24 — a cancelled turn still records its cost | T44, T47, T50 |
| ET-25 — streamed usage is recorded (`include_usage`) | T42, T44, T50 |
| NFR-061a/b, NFR-063 — measured, not modelled | T40, then T50 |

Every M2 FR in `ARCHITECTURE_M2_STREAMING.md` §11.1 is claimed by at least one task above.

---

## 10. What the owner must decide before build starts

1. **Is M2 = streaming + cancellation, with FR-023/FR-025 as M2b?** The plan assumes yes and argues it
   in `ARCHITECTURE_M2_STREAMING.md` §1.3. Folding T48 in is possible; it adds prompt-behaviour risk to
   a transport milestone.
2. **FR-024 says "over WebSocket" and this plan does not build one.** ADR-027 argues it in full,
   including when `/ws/…` becomes right (M5 approvals, M10 schedules). He should confirm he is content
   to overrule his own SRS line rather than have it overruled quietly.
3. **`ChatResponse.outcome` gains `"cancelled"`** — a change to the frozen §6 contract, argued in
   ADR-029. The alternative is reporting a user's deliberate action as `failed`.
4. **NFR-061 is withdrawn as unmeetable-or-meaningless** and replaced by NFR-061a/b (M2§1.2). This is
   the same class of correction as M9-A5: a number in the SRS that the architecture cannot honour as
   written.
5. **He should see T40's result before T41 starts.** If the analysis call is a small share of the
   5.8 s turn, the perceived win from streaming is smaller than M2§8 claims.
