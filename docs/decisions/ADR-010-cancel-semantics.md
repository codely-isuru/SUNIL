# ADR-010 — Cancel is client-side only in M1; the server-side abort seam is built but not wired

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Escalated by:** UI/UX Designer, `docs/design/M1_CHAT_SPEC.md` Assumption 2 and §6, via the Delivery Manager.
**Context refs:** `docs/ARCHITECTURE_V1.md` §11.4, FR-065 (task lifecycle), ADR-005, ADR-009.

## Context

The Designer put a Cancel control inside the working indicator and specified client-side-only
behaviour by default, with copy that is honest about it:

> *"You cancelled this. I'll stop showing progress for it — it won't appear as a reply, even if I
> finish it in the background."*

and asked whether the Architect would wire a real server-side abort, in which case the copy
simplifies to *"Cancelled."*

## Decision

**Client-side only in M1. The Designer's copy stands exactly as written, including the background
clause.**

The deciding reason is scope, not effort. A real cancellation needs a terminal task state that is
neither `completed` nor `failed`. FR-065 specifies the lifecycle as
`pending → in_progress → completed|failed`, and **QA is writing red tests against that enumeration
right now**. Adding `cancelled` means an SRS amendment plus a rewrite of tests that already exist,
three days before the milestone. The cost of not having it is one possibly-wasted turn's tokens
(single-digit cents) and one orphaned *read-only* GitHub call — no side effect, no data change,
because M1 has no write operation at all (ADR-000 Q4/FR-121).

**The seam is built.** `TraceContext.emit()` is already called at all twelve stage boundaries, so
cooperative cancellation is a flag check inside that one method plus a `cancelled` status and a
`POST /api/v1/chat/{request_id}/cancel` endpoint. Contained change, not a refactor. Owed at **M2**
(debt D-4), alongside streaming, where the SRS is being revised anyway.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Cooperative server-side abort in M1** (cancel endpoint + flag checked at each stage boundary) | ~45 minutes of code, and technically attractive. Rejected because it forces a `cancelled` terminal state into FR-065's enumeration and invalidates QA's in-flight tests. The right time is M2, with an SRS change, not a silent divergence. |
| **Rely on client disconnect to cancel automatically** | Tempting — ASGI does deliver `http.disconnect`. Rejected because whether the handler task is actually cancelled depends on server version and configuration, so the behaviour would be unverified, environment-dependent, and would make the user-facing copy a guess. This design does not ship a control it cannot demonstrate. |
| **Remove the Cancel control entirely** | Leaves the user with no exit from a 30 s wait. Worse product for no architectural gain. |
| **Hard-kill the turn (cancel the asyncio task from outside)** | Leaves the task row mid-transition, the trace incomplete and the audit chain broken — actively damaging the ET-6 guarantee to save a few cents of tokens. |

## Consequences

- The Designer's copy is correct and needs no change. **The "even if I finish it in the background"
  clause is load-bearing honesty** and must not be edited out during build for brevity.
- A cancelled turn still completes server-side and still writes its full trace, `llm_calls` and
  `tool_calls` rows. That is fine and arguably useful: the data is captured for §30 either way.
- A cancelled turn's assistant message **is still persisted**. If the owner reloads, it will be in the
  conversation. M1 has no history view (FR-025 is M2), so this is invisible now; M2's history work
  must decide whether to filter it. Recorded so it is not discovered as a bug.
- **Debt D-4:** cooperative server-side cancel + `cancelled` task state, owed at M2.

---

## Superseded in part by ADR-029 — 2026-08-19

**Status: superseded in part.** The M1 decision — cancel is client-side only, and the abort seam exists
unwired — was correct for M1 and its reasoning is unchanged: a synchronous POST gives the server no
cancellation signal it can act on, and inventing one would have meant a cancel endpoint, a cancellation
token and a polling loop, three days from a milestone.

**ADR-027 changes the premise.** With the answer streaming from the POST, a client abort is a TCP
close, and a TCP close is a signal the server can act on. **ADR-029 wires the seam this ADR left**:
disconnect cancels the turn, `TaskStatus.CANCELLED` becomes a real terminal state (migration `0002`),
and `ChatResponse.outcome` gains `"cancelled"`.

This is recorded as a partial supersession rather than a replacement so the M1 decision keeps its
context: **DC-7 and debt D-4 are closed by ADR-029, not by this ADR having been wrong.**
