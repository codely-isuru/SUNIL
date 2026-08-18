# ADR-029 — Cancellation is a client disconnect; `cancelled` becomes a real terminal state

**Status:** Proposed (Architect, M2) · **Date:** 2026-08-19 · **Decider:** Solution Architect
**Supersedes in part:** ADR-010 (cancel is client-side only in M1) — the seam it left is now wired.
**Closes:** DC-7, debt D-4.
**Context refs:** ADR-010, ADR-027; `ARCHITECTURE_V1.md` §11.4, §5.3, §7.3;
`ARCHITECTURE_M2_STREAMING.md` §6; FR-027 … FR-030, NFR-063; ET-23, ET-24.

## Context

ADR-010 made cancel **client-side only** in M1: the browser aborts, stops rendering and shows a
cancelled state; **the server keeps working and keeps spending.** That was the right call for M1 — a
synchronous POST gives the server no cancellation signal it can act on, and inventing one would have
meant a cancel endpoint, a cancellation token and a polling loop, three days from a milestone.

ADR-027 changes the premise. With the answer streaming from the POST, a client abort becomes a TCP
close, and a TCP close is a signal the server can act on.

## Decision

**A client disconnect cancels the turn. There is no cancel endpoint and no cancellation token.**

```
user clicks Cancel
  → AbortController aborts the fetch
  → TCP close → ASGI "http.disconnect"
  → Starlette's StreamingResponse cancels the streaming task
  → asyncio.CancelledError propagates into the turn
  → the provider stream is closed in a `finally` (`async with`)
  → tasks.status = "cancelled"; final_response emitted with outcome "cancelled"
```

### 1. Verified against the installed stack, and the detail is version-dependent

`starlette==1.6.0`'s `StreamingResponse.__call__` branches on the ASGI `spec_version`:

* **`>= (2,4)`** — disconnect surfaces as `ClientDisconnect`, raised from an `OSError` **on the next
  send**.
* **`< (2,4)`** — `listen_for_disconnect(receive)` runs **concurrently** in a collapsing task group and
  cancels the stream **immediately**.

**The pinned `uvicorn==0.52.3` declares `spec_version: "2.3"`** (`h11_impl.py:207`,
`httptools_impl.py:228`), so SUNIL is on the immediate path today. **Recorded as debt D-19**, because
upgrading uvicorn to a version declaring 2.4+ silently changes detection from *immediate* to *on next
send* — the kind of behavioural change that arrives inside a routine dependency bump and is noticed
only as "cancel got slow".

### 2. Which is why the heartbeat is load-bearing, not decoration

A `heartbeat` frame every second guarantees a send attempt is pending within a second, so a disconnect
is noticed within a second **on either Starlette branch**. Without it, on the 2.4+ path, a turn blocked
in a 4-second plan call would not notice the abort until the call returned — which is not cancelling,
it is finishing and then admitting it.

### 3. `cancelled` is a state, not a failure

`TaskStatus` gains `CANCELLED` (verified absent today: `PENDING · IN_PROGRESS · COMPLETED · FAILED`),
enforced by a CHECK constraint — **migration `0002`**.

`ChatResponse.outcome` gains `"cancelled"` beside `"ok"`/`"failed"`. **That is a change to the frozen §6
contract and it is argued, not slipped in:** the alternative is recording a deliberate user action in
the same bucket as a provider outage, which makes the `tasks` table lie about why work stopped and
makes "how often does SUNIL fail?" unanswerable. The four `failure.kind` values are untouched, and
`failure` is `null` on a cancelled turn.

### 4. What is guaranteed, and what is not

**Guaranteed:** no *new* provider attempt starts after cancellation; the in-flight stream is closed;
the turn reaches a terminal recorded state; the tool is not invoked if the plan had not yet reached it.

**Not guaranteed, and stated rather than implied:** an in-flight **tool call** is not aborted. The
GitHub adapter's three concurrent GETs are already bounded by a 15 s timeout, and interrupting an
external read buys nothing — it has already left the machine. Cancellation stops SUNIL from *starting*
more work, not from having started some.

**Also not guaranteed:** money already spent. A turn cancelled during the analysis call has already
paid for its plan call and for the tokens generated so far. **FR-029 requires that spend be recorded**
— the `llm_calls` row is written with the partial text and its real usage (ET-24). Cancellation reduces
waste; it is not a budget control, and DC-5's spend cap remains M3's.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **`POST /api/v1/chat/{request_id}/cancel`** | A second endpoint, a second auth path, a cancellation registry keyed by `request_id`, and a squatting problem identical to the one ADR-009's `TraceBus` had (T-06). All to carry a signal TCP already carries. It is also racy: the cancel can arrive before the turn has registered itself. |
| **A cancellation token in the request, polled by the turn** | Requires the turn to poll something, which means a cadence, which means a worst case — and the worst case is exactly what the heartbeat already bounds, without the token. |
| **Keep ADR-010's client-side-only cancel** | Leaves the server spending on work nobody will see, which is the defect DC-7 and D-4 exist to record. Streaming makes the fix nearly free; declining it would be choosing to keep a known waste. |
| **Report a cancelled turn as `failed`** | Puts a deliberate user action in the same bucket as a provider outage. It makes the `tasks` table lie about why work stopped, and it makes any future reliability metric meaningless. |
| **Report it as `ok` with an empty message** | Worse: it claims a successful turn produced nothing. |
| **Roll back the turn's rows on cancellation** | Destroys the audit trail of work that genuinely happened and money that was genuinely spent — directly against NFR-006 and T-33. A cancelled turn is a *recorded* turn. |
| **A `DELETE` on a turn resource** | REST theatre for a signal the transport already provides. |

## Consequences

* **Migration `0002` belongs to M2.** ⚠️ **M9's `0002_voice` therefore renumbers to `0003`**, and
  `main.py`'s `EXPECTED_ALEMBIC_HEAD` moves twice. Recorded as debt **D-21** and noted in
  `M9_BUILD_PLAN.md` T27, so it is caught by reading rather than by a failed boot.
* `M1_CHAT_SPEC.md` §6's cancel copy stays accurate — the user-visible behaviour is unchanged; what
  changes is that the server now agrees with it.
* **ADR-010 is superseded in part, not withdrawn.** Its reasoning for M1 was sound and its "the abort
  seam exists, unwired" is exactly what this ADR wires. Recorded as a partial supersession so the M1
  decision keeps its context.
* `useTurn`'s existing `cancelTurn()` already calls `abortRef.current?.abort()`. **The frontend change
  is that the abort now means something**, plus rendering the new `cancelled` outcome — the seam T16
  built holds.
