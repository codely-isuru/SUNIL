# ADR-031 — A turn that needs approval ends `parked`; approval runs a system continuation

**Status:** Proposed (Architect, V2 Phase 0) · **Date:** 2026-09-10 · **Decider:** Solution Architect
**Fixes an open point in:** `V2_DEVELOPMENT_PLAN.md` Phase 0 C4 ("park → notify → decide →
resume/refuse" names the lifecycle but not the execution model behind it).
**Deviates from an M1 shape:** the §6 envelope's `outcome: ok|failed` gains `parked` (C5 §2.1).
**Context refs:** ADR-005 (turn runs in-request), ADR-029 (disconnect = cancel), ROADMAP §12,
§26.4, §33.6; contracts C1 §2.1, C4, C5.

## Context

V2 introduces write operations whose permission grant is `ask_user`. The M1 execution model
(ADR-005: the turn runs inside the HTTP request; no queue, no worker, no Redis) cannot hold an HTTP
response open for the hours or days a human decision may take. Something must give: the execution
model, or the idea that one turn is one uninterrupted execution.

## Decision

**The turn gives, not the execution model.** When the Tool Manager's permission step returns
`ASK_USER` with no consumable approval:

1. The approvals service persists — in one transaction — the approval row (explicit
   `status='pending'`) and the **continuation state**: the validated plan, the step cursor, and the
   `args_hash` binding. Only then does the turn return.
2. The turn ends honestly: envelope `outcome="parked"` with the C4 `ApprovalRef`; the task row
   status becomes `parked`. Nothing is left running; the HTTP request completes normally.
3. **Approve** → the API process schedules a **system continuation** (an `asyncio` background task
   in the same process — still no queue, no worker): it consumes the approval (C4's
   `approved→consumed` CAS), executes the approved call through the full C1 pipeline (audit
   included), runs the plan's remaining steps, finalises the task, and appends the assistant
   message to the original conversation under the original lineage (`resumed_from_approval_id`).
4. **Refuse/expire** → no execution; the task is finalised `failed`
   (`approval_refused`/`approval_expired`) with a deterministic, non-LLM assistant message.

Restart safety comes from the persisted continuation state plus the consume CAS: an API restart
between approve and consume re-schedules idempotently at startup (scan for `approved` approvals
with unfinalised tasks); double-execution is impossible because consume is the gate.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Block the HTTP request until decided** | ADR-005's in-request model gives the turn a 40 s deadline (`SUNIL_TURN_DEADLINE_S`); a human decision takes hours. Holding connections open for days is not an option on any timeout budget, and ADR-029 defines disconnect as *cancel* — a browser tab closing would silently cancel a pending approval. |
| **A queue + worker (Celery/Redis/arq) to suspend and resume turns** | Re-introduces exactly the infrastructure ADR-005 removed, for one consumer. The continuation needs to run *once, later, in a process that has the settings and the DB* — an in-process scheduled task plus a startup re-scan gives that with zero new services. Revisit when scheduled workloads (n8n-driven) need real fan-out. |
| **Suspend the coroutine in memory and resume it on decision** | Loses every parked turn on restart/deploy; unbounded memory held per pending approval; untestable resume paths. Persisted-cursor continuation is inspectable in the DB and survives restarts. |
| **Let n8n own suspension (workflow-engine approvals)** | Already rejected in ADR-030 ("SUNIL's own approvals queue is the approval point, not the workflow engine") — approvals are product surface: agent × tool × operation × args, audited in our spine. |
| **Re-run the whole turn from the top on approval** | Re-plans with fresh LLM calls: the owner would approve one plan and execute another — the binding the owner approved (`args_hash`) must be exactly what runs. Also doubles cost. |
| **Keep `outcome: ok|failed` and model parked as `failed`** | Lies to the client and forces the dashboard to special-case a "failure" that is actually the system working as designed. An honest third outcome costs one enum value in a greenfield contract. |

## Consequences

- C5's envelope carries `outcome=parked` + `approval`; C4 §1's transition table is the complete
  state machine; C1 step 3 defines the park/consume seams.
- The continuation is a second entry point into the orchestrator (`run_continuation(state)`)
  beside `run_turn(request)` — both drive the same plan executor, so there is one execution path
  to audit, entered at two points.
- Owner-visible behaviour: a parked task says so in the conversation; the answer to "what happened
  to X?" is in the dashboard queue, never a hung spinner.

---

## Amendment 1 — consume ownership clarified (2026-09-10, Phase 0 fix round)

**Driven by:** QA review 2026-09-10 blocker B3 — as first written, Decision item 3 ("it consumes
the approval … executes the approved call through the full C1 pipeline") and C1 §2.1 step 3 could
each be read as issuing the consume CAS, and a literal implementation consumed twice: the second
consume failed and nothing executed.

**Clarification (one owner):** the continuation does **not** issue the consume CAS itself. It
re-enters `ToolManager.execute(..., approval=<approval_id>)`; the **Tool Manager** recomputes the
binding from freshly re-validated params and calls `ApprovalsService.consume`, which performs the
binding check and the `approved→consumed` CAS in one transaction (C1 §2.1 step 3, C4 §4). Decision
item 3's sentence remains true read at the continuation level — the continuation's call chain
consumes then executes — but the component issuing the CAS is the manager, single chokepoint,
because the binding must be recomputed by the same code that computed it at park time; an
executor-side consume would duplicate C1's validation/canonicalisation steps outside the
chokepoint. The single-use property is unchanged: the CAS inside the ApprovalsService remains the
gate, and restart safety still follows from persisted continuation state + that CAS. The startup
re-scan gains the reconciliation rules recorded in C4 §3 (stale-approved → `approval_expired`;
consumed + unfinalised → `continuation_interrupted`; Security review 2026-09-10 items 1–2).
