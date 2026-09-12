# C4 — Approvals: rationale, in-process seam, and fake

**Version:** 1.2.0 · **Status:** FROZEN (Phase 0, 2026-09-10; last ruling 2026-09-12) · **Owner:** Solution Architect
**OpenAPI:** [`C4-approvals-openapi.yaml`](C4-approvals-openapi.yaml) (the HTTP surface).
**Consumers:** Stream D (dashboard + service), Stream A (the Tool Manager's injected
`ApprovalsService` seam, C1 §2.2), Streams E/F (their write operations park here).
**Related decisions:** ADR-031 (park/resume execution model — the arguments live there),
ROADMAP §12, §26.4, §33.6.

---

## 1. Lifecycle (normative)

```
                    owner approves               consume CAS (Tool Manager,
   park ──▶ PENDING ───────────────▶ APPROVED ── C1 §2.1 step 3) ──▶ CONSUMED
              │  │                      │
              │  │                      └── grace elapsed (sweeper/lazy) ─▶ EXPIRED
              │  │                          (task finalised: failure.kind=approval_expired)
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
state (plan + step cursor + `args_hash`; the `continuation` the orchestrator supplied via C1 §2.2
`ParkContext`, non-empty by construction — v1.1.0, F3), *before* the turn returns `parked` — an API crash after
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

**Post-decision hooks (normative — v1.2.0, ruling R7).** The bullets above state the approve/refuse
after-effects without naming an actor; this names the hook points without widening §4's protocol. A
service that can run an effect exposes it under the conventional name: an awaitable
`finalise_refusal(approval_id)` for the refuse effect (the real service's wrapper over its
`TaskGateway` collaborator) and an awaitable `scheduler.schedule(approval_id)` attribute for the
approve effect (ADR-031's `ContinuationScheduler`). Both are **optional-by-wiring** — present iff
the corresponding collaborator is wired. The HTTP layer invokes each opportunistically after the
decide CAS reports a win; an absent hook is a logged WARNING naming the effect that did not run
(never a failed response — a missing collaborator must not turn the owner's committed decision into
an outage), and a hook that raises is logged with the 200 standing, because the CAS has committed
and the startup reconciliation below (rules 1 and 4) re-derives the effect on the next boot. The §6
fake offers neither hook, and that is conformant: a fake deployment has no task gateway and no
scheduler, and the warning is the honest record of it.

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
4. `refused` or `expired` + unfinalised task → finalise the task `failed` with the matching kind
   (`approval_refused` / `approval_expired`), audited. (v1.2.0, ruling R7 — closes the two windows
   the post-decision hooks leave open: a crash or missing task gateway after a refuse CAS, and a
   decide-time lazy `pending → expired`, whose row leaves the sweeper's pending/approved WHERE
   clauses before the sweep's finalisation pass can ever see it. Idempotent by the same
   `is_finalised` guard as rule 3.)

## 4. In-process seam (injected into the Tool Manager — C1 §2.2)

```python
class ApprovalsService(Protocol):
    async def park(self, req: ParkRequest) -> ParkedApproval: ...
    async def consume(self, approval_id: str, *, binding: ApprovalBinding) -> ConsumeResult: ...

class ParkRequest(BaseModel):
    agent_id: str; tool: str; operation: str
    args_hash: str; params_redacted: dict
    request_id: str; conversation_id: str; task_id: str
    summary: str = Field(min_length=1, max_length=500)
                                      # built by SUNIL code, never LLM output; caps match the
                                      # Approval schema's summary field (v1.1.0, F3)
    continuation: dict = Field(min_length=1)
                                      # opaque persisted plan-cursor state (ADR-031); NEVER empty —
                                      # an empty continuation mints a never-resumable approval
                                      # (v1.1.0, F3)

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

**The protocol is closed; reads are a read model (normative — v1.2.0, ruling R7).** This §4
protocol is the Tool Manager's seam and it stays exactly these two methods. `decide` (§6.2) is a
service-layer decision seam invoked by the HTTP surface — not a protocol method — and the HTTP
reads are not service methods at all: `GET /api/v1/approvals` and `GET /api/v1/approvals/{id}` are
served by a read model over the `approvals` table (`core/approvals/read_model.py`), resolved on the
same engine as C6's reads (one engine resolver, so the queue and the ops reads cannot point at two
databases). §6.5 is a listing **law**: it binds whatever implements a listing — the §6 fake and the
read model alike — and licenses no `list_approvals`/`get` on any protocol. A service implementation
MAY offer convenience reads by delegating to the read model (the real service does), but they are
not contract surface, and no future lane may satisfy a route by widening this protocol — QA wave-1
B1 (`integration-w1.md` §8) is the recorded counter-example: a surface awaiting methods the
contract does not grant answers a conformant service with a 500. The `continuation` column is
structurally excluded from the read model's row mapping, so "never leaves this service over HTTP"
holds for both callers through one column list.

**Provenance (v1.1.0, backend review F3):** `summary` and `continuation` are the two fields the
Tool Manager cannot derive from its own frozen inputs; the orchestrator supplies them through C1
§2.2's `ParkContext` and the manager copies them **verbatim** into the `ParkRequest` it composes.
Every other field is computed by the manager at park time — the identity triple, `args_hash` from
the freshly validated params, `params_redacted`, and the trace ids (one composer, one hasher: C1
§2.1 step 3). The `Field(min_length=…)` constraints above are load-bearing fail-closed checks,
enforced identically by the real service and the fake: a park with an empty `continuation` would
mint exactly the never-resumable approval §5's scope note exists to prevent. `continuation` is
persisted in the park transaction (§1) and never leaves this service over HTTP.

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
   Appends the `ApprovalRequestedEvent` payload to `webhook_sent`. Retains the full `ParkRequest`
   as `self.parked[approval_id]` (v1.1.0, F3 — C1 test 4 asserts `continuation`/`summary`
   provenance against it; the real service persists `continuation` inside the park transaction,
   §1). Empty `summary`/`continuation` are rejected by the `ParkRequest` model itself (§4) — the
   fake inherits that structurally and MUST NOT relax it.
2. `await decide(approval_id, decision, reason=None)` → `Approval | StateConflict | None` — the
   decision seam, the HTTP layer's one mutating call: **awaitable, and the service reads its own
   injected clock** (`now` is not a parameter — clock-ownership rule below). Normative for the
   fake and the real service layer alike (v1.2.0, ruling R7; supersedes v1.0.1's blessing of the
   fake's synchronous caller-supplied-`now` shape, which left the seam uncallable by its only
   production caller — `integration-w1.md` §8.3). Semantics unchanged from v1.0.1: unknown
   `approval_id` → `None`, which the HTTP layer maps to §5's `404 not_found` (already in the
   YAML); `pending` + clock < `expires_at` → transition, set `decided_at` from the clock,
   `decided_by="owner"`, return the row; `pending` + clock >= `expires_at` → transition to
   `expired` first, then return `StateConflict(current_status="expired")` → 409; any other status
   → `StateConflict` carrying it → 409. `decide` never raises for absence or conflict — both are
   return values, so status-code mapping lives in the HTTP layer and nowhere else. An
   implementation MAY accept additional keyword-only parameters with defaults (the real service's
   `decided_by="owner"`); the HTTP layer passes none of them.
3. `consume(approval_id, binding)`: unknown id → `not_found`; status ≠ `approved` →
   `not_approved`; status `approved` but `now >= decided_at + consume_grace_hours` → transition to
   `expired` (lazy) and return `not_approved`; binding tuple ≠ stored tuple (compare all four
   fields) → `binding_mismatch` AND the approval stays `approved` (a mismatch must not burn the
   approval); match within grace → CAS to `consumed`, `ok=True, reason="consumed"`.
4. `sweep(now)`: transitions every `pending` with `expires_at <= now` AND every `approved` with
   `decided_at + consume_grace_hours <= now` to `expired`; returns the total count.
5. Listing: filter by status, order `created_at` desc then id desc; cursor = the last row's id
   (opaque string); `next_cursor=null` when the page is short.

**Clock ownership (normative — v1.2.0, ruling R7).** Time enters an approvals service exactly once:
the clock injected at construction (the fake's `FakeClock`; the real service's
`clock: Callable[[], datetime]`, defaulting to `datetime.now(UTC)` and bound as `:now` into §1's
CAS statements — one clock, one truth for what "expired" means). No HTTP request carries or implies
a clock: the HTTP layer owns none, and a `now` it invented would silently override the service's —
wall-clock time passed into a `FakeClock`-wired service corrupts test determinism, and in
production a caller's clock would re-author the very guard (`expires_at > now`) the decide CAS
exists to enforce. This is the rule §4's `consume` has always embodied (its frozen signature never
carried `now`); v1.2.0 aligns `decide` with it. `sweep(now)` (§6.4) is unchanged and is not an
exception: its `now` is a scheduling/test affordance supplied by an in-process actor (the sweeper
loop, a test) — never an HTTP caller — and the real service accepts it as optional, defaulting to
its own clock.

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
8. fail-closed park material (v1.1.0, F3): constructing `ParkRequest(..., continuation={})` and
   `ParkRequest(..., summary="")` each raise `pydantic.ValidationError` — the seam itself refuses
   to mint a never-resumable approval, independently of the Tool Manager's `park_context`
   precondition (C1 §2.1 / C1 test 8).

## Changelog

- **v1.2.0 — 2026-09-12 (wave-2 opening ruling — R7 in `docs/tasks/integration-w1-rulings.md`,
  resolving `integration-w1.md` §8.3).** **§6.2: the decision seam is
  `await decide(approval_id, decision, reason=None) -> Approval | StateConflict | None` —
  awaitable, service-owned clock; the caller-supplied `now` and the synchronous form are
  removed.** §6: clock-ownership paragraph (one clock per service, injected at construction; no
  HTTP caller supplies time; `sweep(now)` unchanged as a scheduling/test affordance). §3:
  post-decision hooks named normatively (`finalise_refusal(approval_id)` /
  `scheduler.schedule(approval_id)` — optional-by-wiring, warn-don't-fail after a committed CAS,
  blessing the wave-1 route's posture) and startup-reconciliation **rule 4** added
  (`refused`/`expired` + unfinalised task → finalise, closing the refuse-crash and
  decide-lazy-expiry windows). §4: protocol-closure + read-model paragraph — list/get are
  read-model operations, never protocol methods (the normative reading of the QA wave-1 B1 fix,
  so no future lane re-widens the protocol).

  **Why MINOR, not MAJOR.** C4's consumer-facing surfaces are the §4 protocol (Stream A's
  Tool-Manager seam: `park`/`consume`) and the OpenAPI HTTP surface — both byte-unchanged, and
  the HTTP decision path becomes implementable exactly as the YAML specifies (the
  extra-contractual 501 posture retires). What moves is §6.2, whose v1.0.1 shape was blessed
  FROM the fake and has exactly one production caller — the HTTP layer — which **could not call
  it** (the recorded 501): a seam uncallable by its only caller has no working consumer for a
  MAJOR bump to protect. The §6.2 clauses consumers do rely on — the return union, never-raise,
  status mapping living in the HTTP layer — are preserved verbatim. Every in-repo caller of the
  old fake shape is enumerated and migrated by the parcels below; version numbers are for
  consumers, and signalling Stream A or the dashboard that something they consume moved would be
  false.

  **Migration (v1.1.0 → v1.2.0) — two parcels, and one ordering rule: the ATOMIC SET (parcel 1
  + parcel 2's two test edits) must enter the integration tree together; parcel 2's route
  deletion lands any time AFTER the atomic set** (the current route's `iscoroutinefunction`
  probe starts using the fake's new awaitable `decide` the moment it lands — turning the fake-
  wired 501 into contract answers — so the 501 branch is dead code from that commit on, but the
  old harness line and the 501-asserting test go red at the same moment and must move with it).

  *Parcel 1 — QA (its ownership: `tests/fakes/`, `tests/contracts/`).*
  `tests/fakes/fake_approvals.py::FakeApprovalsService.decide` becomes
  `async def decide(self, approval_id: str, decision: Literal["approve", "refuse"], reason: str | None = None) -> Approval | StateConflict | None`
  with `now = self.clock.now()` as the body's first read of time — otherwise byte-identical
  (full replacement body in ruling R7); rewrite the module-docstring bullet claiming `decide`
  is synchronous with caller-`now` (sweep's half stays true). Call sites, mechanical —
  `X.decide(a, d, r, <clock>.now())` → `await X.decide(a, d, r)`, every enclosing test already
  `async`: `tests/contracts/test_c4_approvals.py` lines 108, 134, 135, 142, 143, 149, 158, 183,
  220, 241, 242, 292, 300, 311, 325, 332, 349 (17); `tests/contracts/test_c1_tool_adapter.py`
  lines 557, 797 (2).

  *Parcel 2 — wiring engineer (backend estate).*
  `sunil/core/approvals/service.py`: **no change** — `DatabaseApprovalsService.decide`
  (`service.py:446`) already implements the ruled shape (awaitable, `self._now()`, keyword-only
  `decided_by="owner"` permitted by §6.2). Atomic-set test edits:
  `tests/unit/approvals/harness.py:63` → `return await self.service.decide(approval_id,
  decision, reason)` (FakeHarness.decide becomes identical to DbHarness.decide — that identity
  is the parity point); `tests/unit/approvals/test_mounted_surface.py::
  test_the_mounted_decision_names_the_gap_when_the_seam_has_no_service_decide` (:259) is deleted
  and replaced by the fake-wired green decision test (body in R7) — closing QA's recorded "no
  green coverage on the bootable configuration's decision path". Route deletion (after the
  atomic set): in `sunil/api/routes/approvals.py` delete `service_decide` (:291-318),
  `DECISION_SEAM_MISSING` + its comment block (:321-333), the now-unused
  `from inspect import iscoroutinefunction` (:60), and the module docstring's 501 status-table
  row (:41); in `decide_approval`, replace the probe + 501 branch (:461-467) with
  `service = get_approvals_service(request)` then
  `result = await service.decide(approval_id, body.decision, body.reason)` — a wired seam whose
  `decide` is not awaitable is henceforth a wiring defect (same 500 class as
  `approvals_service` unset, per `get_approvals_service`'s recorded posture). Same-wave
  follow-up owed: implement §3 reconciliation rule 4 in
  `DatabaseApprovalsService.reconcile_on_startup` (+ a `ReconciliationReport` bucket + test).

- **v1.1.0 — 2026-09-10 (backend fakes-review round, F3).** §4: provenance paragraph —
  `summary`/`continuation` are supplied by the orchestrator via C1 §2.2 `ParkContext` and copied
  verbatim by the Tool Manager, which computes every other field (one composer, one hasher);
  `summary` gains `Field(min_length=1, max_length=500)` (matching the Approval schema) and
  `continuation` gains `Field(min_length=1)` — fail-closed against minting a never-resumable
  approval, the exact hole the backend probe demonstrated (`continuation={}` passed the suite).
  §1 restart-safety cross-references the provenance. §6 behaviour 1: fake retains
  `self.parked[approval_id]` for C1 test 4's provenance assertions; new contract test 8 pins the
  model-level rejection of empty park material. MINOR: the seam's method set and the HTTP surface
  are unchanged; the constraints add normative validation behaviour that v1.0.x's own restart-safety
  rule already presupposed (a real, resumable continuation). No transition, CAS or single-use
  property touched — Security's verified-sound list preserved.

- **v1.0.1 — 2026-09-10 (C3-scope round).** §6 behaviour 2: `decide`'s return shape specified
  normatively as `Approval | StateConflict | None` with `None` = unknown id → HTTP 404 (the YAML
  already carried the 404; the in-process shape was unspecified). Blesses the QA fakes-build
  judgment call recorded in `docs/tasks/P0-fakes.md` — patch: clarification of the fake/service
  layer, no change to the §4 seam (`park`/`consume`) or the HTTP surface.

- **v1.0.0 — 2026-09-10 fix round** (pre-merge; version unchanged because the freeze was never
  merged). Consume ownership: `approved→consumed` actor corrected to the Tool Manager via
  `ApprovalsService.consume`; §3's duplicate executor-side consume path deleted (QA review B3,
  ADR-031 Amendment 1). Consume CAS grace-bounded + `approved→expired` transition + startup
  reconciliation rules added (Security review items 1–2). `summary`/`params_redacted` plain-text
  rendering rule (Security item 8). Scope note recording the deliberate absence of
  `POST /api/v1/approvals` (QA should-fix). Fake: `consume_grace_hours` constructor, lazy
  stale-approved expiry, contract test 7.
