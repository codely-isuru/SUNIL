# C4 — Approvals: rationale, in-process seam, and fake

**Version:** 1.0.0 · **Status:** FROZEN (Phase 0, 2026-09-10) · **Owner:** Solution Architect
**OpenAPI:** [`C4-approvals-openapi.yaml`](C4-approvals-openapi.yaml) (the HTTP surface).
**Consumers:** Stream D (dashboard + service), Stream A (the Tool Manager's injected
`ApprovalsService` seam, C1 §2.2), Streams E/F (their write operations park here).
**Related decisions:** ADR-031 (park/resume execution model — the arguments live there),
ROADMAP §12, §26.4, §33.6.

---

## 1. Lifecycle (normative)

```
                    owner approves                continuation CAS
   park ──▶ PENDING ───────────────▶ APPROVED ──────────────▶ CONSUMED
              │  │
              │  └── owner refuses ─▶ REFUSED   (task finalised: failure.kind=approval_refused)
              └──── TTL sweeper ────▶ EXPIRED   (task finalised: failure.kind=approval_expired)
```

**Complete transition set** (guard-invariant rule — memory lesson 2026-08-05: enumerate every
transition the invariant must survive; anything not listed is impossible by construction):

| From → To | Actor | Mechanism |
|---|---|---|
| (none) → `pending` | Tool Manager, via `ApprovalsService.park` (C1 §2.1 step 3) | `INSERT` with **explicit** `status='pending'` — the column has NO schema default (memory lesson 2026-08-17: a state column whose creation paths omit it reads as its default; here an omitting path is an error, never a decided row) |
| `pending` → `approved` | owner via `POST …/decision` | `UPDATE … SET status='approved', decided_at=now(), decided_by=:owner WHERE id=:id AND status='pending' AND expires_at > now()` — zero rows ⇒ 409 |
| `pending` → `refused` | owner via `POST …/decision` | same CAS shape |
| `pending` → `expired` | TTL sweeper (startup + every 60 s) and lazily at read/decide time | same CAS shape (`WHERE status='pending' AND expires_at <= now()`) |
| `approved` → `consumed` | **Tool Manager**, via `ApprovalsService.consume` inside the continuation's `execute` call (C1 §2.1 step 3 — the manager is the single consume owner; the continuation executor never issues this CAS itself. Fix round 2026-09-10, QA B3 / ADR-031 Amendment 1) | `UPDATE … SET status='consumed', consumed_at=now() WHERE id=:id AND status='approved' AND decided_at + :grace > now()` — zero rows ⇒ C1 `approval_invalid`, nothing executes. `:grace` = `SUNIL_APPROVAL_CONSUME_GRACE_HOURS` (default 1) — an `approved` row is consumable only within the grace window after the decision (Security review 2026-09-10 item 1) |
| `approved` → `expired` | TTL sweeper (same schedule) and lazily at consume time | `UPDATE … SET status='expired' WHERE status='approved' AND decided_at + :grace <= now()` — catches stale approvals after downtime AND `binding_mismatch` rows nobody re-consumed (Security review 2026-09-10 item 1) |

No transition out of `refused`, `expired`, or `consumed` exists. Rows are never deleted (audit).
Restart safety: the park `INSERT` commits in the same transaction as the persisted continuation
state (plan + step cursor + `args_hash`), *before* the turn returns `parked` — an API crash after
park loses nothing; an approved-but-unconsumed approval is re-consumable by the restarted
continuation because consume is the CAS, not an in-memory flag.

**Single-use binding:** an approval authorises exactly one execution of
`(agent_id, tool, operation, args_hash)`. The continuation re-validates params and recomputes
`args_hash`; a mismatch (drifted config, re-validated plan producing different args) is
`approval_invalid` — the owner approved *those arguments*, not the operation in general.

**No service-level bypass mode (structural).** There is no auto-approve flag, no log-only mode, no
"approvals disabled" switch on this service (memory lesson 2026-08-17: a single mode scalar over a
mixed population grants the soak to the population that must never have it). The only way an
operation stops parking is its `permissions.yaml` grant moving `ask_user → allow` for that exact
`agent × tool × operation` triple — a per-population config change reviewed like code, evaluated in
the permission engine *before* this service is ever reached, so no value in *this* service's config
can weaken it.

## 2. Notify

Two channels, both after the park transaction commits:
1. **Dashboard queue** (source of truth): Stream D polls `GET /api/v1/approvals?status=pending`
   every 10 s. No push channel in Phase 0/1 (ADR-027's V-10 argument: unsolicited push arrives with
   a later milestone).
2. **Webhook** (optional): one `approval.requested` POST to `SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL`
   (loopback or Compose host `n8n` only — ADR-033 URL rule), 3 retries (1 s/5 s/25 s), failures
   logged + audited, never blocking. Payload is the redacted summary schema — params never leave
   through this channel.

## 3. Resume / refuse semantics

Argued in ADR-031 (+ Amendment 1); the contract facts:

- **Approve** → the decision endpoint returns immediately; the approvals service schedules the
  **continuation**: a system-initiated execution that re-enters
  `ToolManager.execute(..., approval=<approval_id>)`. The **manager** recomputes the binding from
  re-validated params and calls `consume` (C1 §2.1 step 3) — the approved→consumed CAS happens
  inside this service, invoked by the manager, and nowhere else. The pipeline then executes the
  approved call (audit included), continues the persisted plan's remaining steps and finalises the
  task. The continuation appends its assistant message to the original conversation with the
  original `request_id` lineage (`resumed_from_approval_id` on the audit rows). (Fix round
  2026-09-10, QA B3: this section previously ALSO had the continuation issuing the consume CAS
  before calling the Tool Manager — that duplicate path is deleted; one consume owner.)
- **Refuse** → no execution. The task is finalised `failed` with C5 `failure.kind="approval_refused"`;
  a deterministic (non-LLM) assistant message records the refusal in the conversation.
- **Expire** → identical to refuse with `failure.kind="approval_expired"`.

**Startup reconciliation (normative — Security review 2026-09-10 items 1–2).** The ADR-031 startup
re-scan applies exactly these rules, each transition audited:

1. `approved` + unfinalised task + within grace → re-schedule the continuation (ADR-031, unchanged).
2. `approved` + `decided_at + grace <= now()` → transition to `expired` (table above) and finalise
   the task `failed` with `failure.kind="approval_expired"`.
3. `consumed` + unfinalised task (crash between the consume CAS and task finalisation) → finalise
   the task `failed` with `failure.kind="continuation_interrupted"` (C5 failure kind) and write an
   `audit_events` row of kind `continuation_reconciled`. The tool call may or may not have fired —
   the two-phase audit attempt row (C1 §2.1 step 4) is the record of what was attempted; the
   reconciliation NEVER re-executes, because the consume CAS is spent and single-use is the
   property that must survive a crash.

## 4. In-process seam (injected into the Tool Manager — C1 §2.2)

```python
class ApprovalsService(Protocol):
    async def park(self, req: ParkRequest) -> ParkedApproval: ...
    async def consume(self, approval_id: str, *, binding: ApprovalBinding) -> ConsumeResult: ...

class ParkRequest(BaseModel):
    agent_id: str; tool: str; operation: str
    args_hash: str; params_redacted: dict
    request_id: str; conversation_id: str; task_id: str
    summary: str                      # built by SUNIL code, never LLM output
    continuation: dict                # opaque persisted plan-cursor state (ADR-031)

class ParkedApproval(BaseModel):
    approval_id: str; expires_at: str

class ApprovalBinding(BaseModel):
    agent_id: str; tool: str; operation: str; args_hash: str

class ConsumeResult(BaseModel):
    ok: bool
    reason: Literal["consumed", "not_found", "not_approved", "binding_mismatch"] | None
```

Both methods have exactly one caller: the Tool Manager (C1 §2.1 step 3). `consume` performs the
binding check and the `approved → consumed` CAS (grace-bounded, §1) in one transaction; `ok=False`
maps to C1 `approval_invalid`. A stale-approved consume (past grace) lazily expires the row and
returns `not_approved`.

**`summary` rendering rule (normative for Stream D — Security review 2026-09-10 item 8):**
`summary` is built by SUNIL code but embeds attacker-influenceable values (repo names, issue
titles, third-party strings that arrived in params). The dashboard MUST render it as **plain text
only** — never HTML, never markdown, never interpolated into the DOM as markup. The same rule
applies to `params_redacted` values and to the webhook payload's `summary`.

## 5. Error semantics (HTTP)

Defined in the YAML: `401 unauthenticated`, `403 forbidden_client` (header/Origin), `404
not_found`, `409 state_conflict` carrying `current_status` (the ONLY conflict shape — expiry at
decision time is a 409 with `current_status=expired`, not a separate 410), `422 validation_error`.
Decision idempotency is deliberately NOT provided: repeating a decision returns 409 so the UI
must show the true state rather than a comforting echo.

**Scope note — why there is no `POST /api/v1/approvals` (fix round 2026-09-10, QA should-fix).**
The development plan's Phase 0 sketch listed an approval-creation endpoint; it is deliberately not
built, and this is the recorded scope change to that plan. Approvals are minted exclusively by the
in-process `park` seam (§4), inside the park transaction that also persists the continuation state
(§1, ADR-031). An HTTP creation surface would let a caller mint approval rows with no persisted
continuation and no Tool-Manager-computed `args_hash` — an approval that could never be consumed
correctly, or worse, one whose binding the server did not compute. The only mutating HTTP endpoint
is the decision.

## 6. FAKE specification — `FakeApprovalsService` + fixture data (QA-buildable, no questions)

Module: `apps/api/tests/fakes/fake_approvals.py`. Implements `ApprovalsService` AND provides the
HTTP layer's store so Stream D can build the dashboard against a running fake.

Constructor: `FakeApprovalsService(consume_grace_hours=1)` (mirrors
`SUNIL_APPROVAL_CONSUME_GRACE_HOURS`). In-memory `dict[str, Approval]`; ids `apr-1`, `apr-2`, … in
park order; `created_at` from an injectable clock (default start `2026-01-01T00:00:00Z`, +1 s per
park); `expires_at = created_at + 72h`; webhook calls recorded in `self.webhook_sent: list[dict]`
(no real HTTP).

Exact behaviours:
1. `park(req)` → new approval, `status="pending"` set explicitly, returns `ParkedApproval`.
   Appends the `ApprovalRequestedEvent` payload to `webhook_sent`.
2. `decide(approval_id, decision, reason, now)` (used by the fake HTTP layer):
   `pending` + `now < expires_at` → transition, set `decided_at=now`, `decided_by="owner"`, return
   row. `pending` + `now >= expires_at` → transition to `expired` first, then return
   `state_conflict(current_status="expired")`. Any other status → `state_conflict` with it.
3. `consume(approval_id, binding)`: unknown id → `not_found`; status ≠ `approved` →
   `not_approved`; status `approved` but `now >= decided_at + consume_grace_hours` → transition to
   `expired` (lazy) and return `not_approved`; binding tuple ≠ stored tuple (compare all four
   fields) → `binding_mismatch` AND the approval stays `approved` (a mismatch must not burn the
   approval); match within grace → CAS to `consumed`, `ok=True, reason="consumed"`.
4. `sweep(now)`: transitions every `pending` with `expires_at <= now` AND every `approved` with
   `decided_at + consume_grace_hours <= now` to `expired`; returns the total count.
5. Listing: filter by status, order `created_at` desc then id desc; cursor = the last row's id
   (opaque string); `next_cursor=null` when the page is short.

Contract tests (`apps/api/tests/contracts/test_c4_approvals.py`):
1. park → pending; decide approve → approved; consume with matching binding → consumed; second
   consume → `not_approved` (single-use proven).
2. decide on approved/refused/expired/consumed → 409 `current_status` correct in all four cases.
3. consume with one field of the binding changed (each of the four, four cases) →
   `binding_mismatch`, status still `approved`; the SAME approval then consumes successfully with
   the correct binding (proves the mismatch burned nothing).
4. expiry: park, advance clock 73 h, decide → 409 `expired`; sweep counts it exactly once.
5. two concurrent decides (sequential calls simulating the race) → exactly one wins, second gets 409.
6. webhook payload contains NO `params_redacted` key (redaction-by-shape probe).
7. stale-approved (Security review 2026-09-10 item 1): park, approve, advance clock past
   `consume_grace_hours`, consume with the CORRECT binding → `ok=False, reason="not_approved"` and
   the row is `expired`; a second park+approve consumed within grace succeeds. `sweep` also expires
   a stale `approved` row it reaches first. (The startup reconciliation of `consumed`+unfinalised
   tasks — §3 rule 3 — is orchestrator-level and is tested with the continuation executor in
   Phase 2, not against this fake alone.)

## Changelog

- **v1.0.0 — 2026-09-10 fix round** (pre-merge; version unchanged because the freeze was never
  merged). Consume ownership: `approved→consumed` actor corrected to the Tool Manager via
  `ApprovalsService.consume`; §3's duplicate executor-side consume path deleted (QA review B3,
  ADR-031 Amendment 1). Consume CAS grace-bounded + `approved→expired` transition + startup
  reconciliation rules added (Security review items 1–2). `summary`/`params_redacted` plain-text
  rendering rule (Security item 8). Scope note recording the deliberate absence of
  `POST /api/v1/approvals` (QA should-fix). Fake: `consume_grace_hours` constructor, lazy
  stale-approved expiry, contract test 7.
