# integration-w1-rulings — wave-1 rulings batch (six items) + R7 (wave-2 opening ruling)

**Branch:** `task/integration-w1` · **Lane:** solution_architect · **Date:** 2026-09-12
**Scope:** the six non-blocking items accumulated by the wave-1 reviews (`qa-wave-w1.md`,
`integration-w1.md`, the security wave verdict in the portal trail), ruled before the merge record
closes. Every ruling names its rejected alternative. Nothing here changes application code; where a
ruling requires code, it names the applier — QA B1 (the C4 Protocol widening) is **not** in this
batch; it has its own architect ruling ask and is being handled with the backend lane's concurrent
fix round.

| # | Item | Instrument |
|---|---|---|
| R1 | QA S2 — `agents.yaml` grants test-only `fake_tool` | This file + one ruling comment in `config/agents.yaml` |
| R2 | Alembic open item — `db/models.py::Approval` unused ORM class | This file (applier: wave-2) |
| R3 | Security LOW — two Origin semantics | **ADR-008 Amendment 1** (dated) |
| R4 | Web D-F3 — audit view renders raw `conversation_id` | This file + closure note in `S-D-web.md` §5 |
| R5 | QA N1 — frozen suite imports lane-owned `ops_harness.py` | **`P0-contracts.md` freeze-scope ruling** (dated append) |
| R6 | ARCH §5 inventory gaps (QA S1) + security wave C-1/C-3 | **ARCHITECTURE_V2 §5** dated append + **THREAT_MODEL §9** (DC-20 + conditions block) |
| R7 | integration-w1 §8.3 — `decide`'s callable shape / clock ownership (wave-2 opening, 2026-09-12, branch `task/S2-rulings`) | **C4 v1.2.0** (§6.2 + §3 + §4 + clock paragraph + changelog migration) |

---

## R1 — the `fake_tool` grant stays: structurally inert in real wiring (QA S2)

**Ruling:** the grant is **documented-inert-in-prod**, and that is *structurally* true, not a
posture: in this architecture an `agents.yaml` grant can only **narrow** what the adapter-built
catalogue offers, never add to it. Four independent layers, verified in code:

1. `plan_schema.py:66` — the LLM-facing `tool` enum is `sorted(catalogue.operations_by_tool)`,
   built from the **catalogue**, not from grants; `main.py:87` builds that catalogue
   `ToolCatalogue.from_adapters(...)` from the wired adapters. Real wiring has no `fake_tool`
   adapter, so a strict-structured-output model cannot even emit the string.
2. `plan_validator.py:204-208` — a planned step must pass `catalogue.has_tool` /
   `has_operation` **before** the grant is consulted (:218). A non-strict model that emits
   `fake_tool` anyway is rejected **at plan validation (layer 4)** — early, with a named error.
   QA S2's "fails late instead of at plan validation" concern is therefore not reachable: the
   late-failure path requires an adapter that only the test `Seams` can inject, and wiring rule 1
   ("production code never imports a test double") forbids exactly that.
3. No `permissions.yaml` triple exists — the C1 chokepoint default-denies (QA's own probe).
4. No `fake_tool` adapter exists outside `tests/fakes/` — nothing could execute.

The grant is load-bearing for the spine's governed-turn evidence (`tests/integration` points
`SUNIL_CONFIG_DIR` at the repo `config/`; removing it fails 9/13), and `agents.yaml`'s own header
already states the principle that makes this safe: *a planning grant must not imply execution
authority*.

**Follow-up owed (wave-2, spine lane, small):** QA's real observation stands — `load_registries`
cross-validates nothing in the grants→tools direction. Add a **startup warning** (not a refusal —
this exact file is a legal state) when an `agents.yaml` grant names a tool absent from the wired
catalogue, so an operator typo (`github` → `githbu`) is a log line, not a silent never-plannable
tool.

**Rejected alternative:** a test-scoped config overlay (second config root or merge layer).
Rejected because it buys nothing the intersection doesn't already guarantee, and costs a
config-resolution order that must itself be tested and documented — against ADR-016's mounted,
single-directory config model. Also rejected: quiet deletion (fails the spine's integration
evidence, per QA).

**Instrument:** this record + the one-line ruling comment in `config/agents.yaml` (done this
commit).

---

## R2 — delete `db/models.py::Approval`, and fence `approvals` out of autogenerate (Alembic round open item)

**Ruling: delete the class — but the deletion is only safe paired with an autogenerate exclusion.**
The mechanics, verified:

- `db/alembic/env.py` targets `Base.metadata` and wildcard-imports `db/models.py`, so the ORM
  `Approval` (VARCHAR timestamps, `ix_approvals_status_expires`) is the **only** `approvals`
  definition autogenerate sees — and it disagrees with the deployed table
  (`core/approvals/table.py`: TIMESTAMPTZ, four indexes; migration `d4approvals0001`), so every
  future autogenerate emits ALTERs toward the wrong shape.
- Stream D's real table lives on a **private** `APPROVALS_METADATA` (a recorded parallel-worktree
  decision in `table.py`'s docstring) — invisible to autogenerate by design.
- Therefore deleting the class **alone** flips the poison, it doesn't remove it: metadata then has
  no `approvals` while the database does, and autogenerate emits `op.drop_table("approvals")` — a
  silent DROP of an audit-bearing table.

**What the applier does (wave-2 wiring round, backend lane):**

1. Delete `db/models.py::Approval` (class at `:326`) and the module-docstring bullet (`:18`) that
   claims the module holds C4's persisted shape — that claim is false against the deployed schema
   (`0001_spine.py:16` already records the disagreement).
2. In `db/alembic/env.py`, add an `include_object` (or `include_name`) hook excluding the table
   name `approvals` on **both** the metadata and reflection sides, with a comment naming
   `core/approvals/table.py` + Stream D's hand-written revisions as the owner. This is what makes
   step 1 safe.
3. Re-point or retire the `Approval` tests in `tests/unit/test_db_models.py` (`:17,:77,:98,:131`)
   — the true shape is already pinned by `tests/unit/approvals/test_migration_matches_table.py`
   and `test_real_service_contract.py`. Production code is untouched: `core/approvals/service.py`
   and `routes/approvals.py` import `Approval` from `core/approvals/base` (the C4 wire model), not
   from `db/models`.

**Rejected alternative:** keep the class behind the `include_object` exclusion alone. Rejected
because the exclusion only silences autogenerate — it preserves a second, false definition of a
production table in the codebase (the docstring's "one representation, no format drift" claim is
contradicted by the deployed TIMESTAMPTZ schema), and a lying model is the drift generator the
exclusion merely hides. Also rejected: attaching `approvals_table` to `Base.metadata` — reverses a
recorded Stream D isolation decision, and autogenerate must never manage a table owned by
hand-written revisions.

---

## R3 — one Origin rule: absent `Origin` is a mismatch, everywhere (Security wave-1 LOW)

**Ruling:** **ADR-008 Amendment 1** (normative instrument, dated 2026-09-12 — see
`docs/decisions/ADR-008-frontend-api-topology.md`). One rule for every route that applies the CSRF
pair: an absent `Origin` is a mismatch → `403 forbidden_client`, and the comparison never
soft-skips on unset `web_origin`. **The lane that moves is Stream D's**
`routes/approvals.py::require_web_client` (single move point — `tasks.py`/`audit.py`/`activity.py`
import the lane from there), **in the wave-2 wiring round** (the file is under concurrent edit in
the wave-1 close; the spine's `require_client_header` is already conformant). Blast radius: one
observable matrix row (`cookie + header + absent Origin`: 200 → 403 on C4/C6 routes);
`tests/ops_harness.py` already sends `Origin`; no contract version moves (C4 §5 and C6 §1 both
defer to ADR-008, which now closes the point).

**Rejected alternative (named in the amendment):** harmonising on the tolerant letter of the
original Decision — silently degrades the two-control pair to one header and loosens the spine's
shipped, C5-§3-recorded posture.

---

## R4 — audit view keeps the raw `conversation_id` for v1; `conversation_label` is a C6 v1.1.0 candidate (Web D-F3)

**Ruling: keep the id; C6 stays 1.0.x this wave.** Grounds:

- The audit view's job is forensic (spec §10: `request_id` is the primary way in); the id is the
  information — copy-pastable, joinable, honest. The owner's lean ("all info visible") is satisfied
  by the id: nothing is hidden, nothing is invented. Stream D's own fidelity table records that an
  invented label was *removed* to reach C6 conformance (S-D-web drift 2) — re-adding one mid-merge
  would reverse a correct call.
- `conversation_label` **is** a legitimate v1.1.0 additive field, and it needs a join:
  `AuditTurn.conversation_label: string|null` sourced from `conversations.title` through the
  turn's task. Two facts bound it: `conversations.title` is **nullable** (`db/models.py:145`), so
  a label can only ever supplement the id, never replace it — withholding it costs no
  information; and `list_audit_turns` is the paged hot path, so the join must live in the page
  query, not per-row.
- **When it moves (the audit-UX round, wave 2+):** C6 minor bump to 1.1.0 with a changelog entry;
  `FakeOpsStore` seed helper extended; engine join; web type + column. Not before.

**Rejected alternative:** bump C6 to 1.1.0 inside the wave-1 merge — a contract version bump, fake
extension, engine join and web change, mid-merge, to relabel a working view with a field that can
be null anyway.

**Instrument:** this record; closure note appended to `S-D-web.md` §5 (D-F3). C6 changelog only
when the field actually moves.

---

## R5 — harness modules serving frozen suites are change-controlled, by name (QA N1)

**Ruling:** blessed with a rule, not relocated — see the dated **freeze-scope ruling appended to
`docs/tasks/P0-contracts.md`** (the file that owns the freeze convention). Named list (currently
exactly `apps/api/tests/ops_harness.py`); edits to a listed module are treated as contract-file
diffs (QA sign-off required even when `tests/contracts/` is untouched); each listed module's
construction semantics must stay pinned by a wiring test outside the frozen suite
(`tests/unit/test_app_wiring.py` today); list extended only by a dated edit in the same PR that
introduces the import.

**Rejected alternative (named there):** relocation into `tests/contracts/` — grows the frozen
surface with lane-owned wiring, forks QA's accepted "one definition of a signed-in owner", and
answers an unreviewed-drift risk with a file move instead of a review rule.

---

## R6 — inventory append (QA S1) + security wave conditions into the deferred register

**Ruling and instrument:** dated appends, both done this batch.

- **`ARCHITECTURE_V2.md` §5**: rows added for `SUNIL_APPROVALS_SWEEPER_ENABLED` (default `true`,
  kill-switch semantics per integration-w1 §4), `SUNIL_TOOL_MANAGER` and `SUNIL_APPROVALS_SERVICE`
  (seam selectors, default `real`; `fake` unreachable from config alone — wiring rule 1), plus a
  dated ruling note. Sweep evidence: all 14 `SUNIL_*` `Settings` fields and `api/wiring.py`'s four
  selectors checked against the table — these three were the only gaps;
  `SUNIL_APPROVAL_CONSUME_GRACE_HOURS` was already present (2026-09-10 row). The `.env.example`
  half of S1 is the backend lane's concurrent fix (their file this round), deliberately not
  touched here.
- **`THREAT_MODEL.md` §9**: **DC-20** — login throttling/lockout as a **pre-condition of the first
  beyond-loopback exposure** (substance from integration-w1 §7.2, Security wave-1) — plus a dated
  conditions block: C-2 recorded fixed (`76d41e3`); **C-1/C-3 registered as named wave-2
  requirements**, with verbatim transcription from the DM's forthcoming `docs/reviews/` mirror as
  **step 0 of wave-2's security checklist**. The verbatim texts live only in the portal trail at
  the time of this append; the register binds the obligation now so the requirements are inherited
  as names, not chat history. **DM action on committing the mirror:** paste C-1/C-3 verbatim into
  that block.

**Rejected alternative:** waiting for the reviews mirror before registering anything — leaves the
conditions as chat history across the wave boundary, which is the exact failure the register
exists to prevent.

---

## R7 — the decision seam is `await decide(approval_id, decision, reason=None)`; the service owns its clock (wave-2 opening ruling, 2026-09-12)

**Question** (recorded in `integration-w1.md` §8.3 — this is the architect ask the wave-1 batch's
scope note deferred, descending from QA B1): C4 §6.2 declared
`decide(approval_id, decision, reason, now)` — synchronous, caller-supplied `now` — a shape blessed
in v1.0.1 *from the fake*, which the HTTP layer cannot call: it owns no clock, and one it invented
would override the service's. The wave-1 route therefore answered 501 on a seam without an
awaitable `decide`, leaving the C4 decision path with no green coverage in the bootable
configuration (QA's recorded observation).

**Ruling — option (a) + async, now C4 v1.2.0 §6.2:**

```python
async def decide(
    approval_id: str,
    decision: Literal["approve", "refuse"],
    reason: str | None = None,
) -> Approval | StateConflict | None
```

The service reads its constructor-injected clock (`FakeClock` in the fake; `datetime.now(UTC)`
default in `DatabaseApprovalsService`, bound as `:now` into §1's CAS). Return-shape semantics —
the union, never-raise, status mapping in the HTTP layer — are preserved verbatim from v1.0.1.
Implementations may add keyword-only defaults (the real service's `decided_by="owner"`); the HTTP
layer passes none.

**Grounds.** (1) *Single-clock truth*: the decide CAS guards `expires_at > now` — that `now` must
have one author, and C4 already chose the author when §4's `consume` was frozen without a `now`
parameter and when the service's injectable-clock design bound one clock into the SQL. A
caller-supplied `now` is a second authority over "expired". (2) *Fake determinism is preserved by
the same mechanism, not lost*: the fake's clock is injected precisely so the service can own time
deterministically — its `consume` has always read it; `decide` now does the same, and tests steer
time via `clock.advance(...)` exactly as they already do for consume/sweep. (3) *The evidence was
already in the tree*: `DatabaseApprovalsService.decide` (`service.py:446`) has implemented the
ruled shape since wave 1 — this ruling moves the contract to the sound implementation, not the
reverse — and every frozen-suite call site passes `<the fake's own clock>.now()` as the fourth
argument, i.e. the caller-`now` was never information, only ceremony. (4) The 501 posture was the
correct wave-1 refusal to guess; ruling the shape is what deletes it.

**Rejected alternatives, by name:**

- **(b) keep caller-supplied `now` and define whose clock the HTTP layer passes.** Any clock the
  HTTP layer could name is the system wall clock — which desynchronises from a `FakeClock`-wired
  service in every test (the exact corruption §8.3 records) and re-authors the CAS guard in
  production. There is no third clock to nominate; the option reduces to "two clocks, pick per
  call", which is the defect class.
- **(c-sync) a synchronous protocol shape.** The real service's decide is necessarily async (a CAS
  over an async engine); a sync contract would force either a thread hop in the decision hot path
  or the fake's accident onto the production service. The protocol names one shape and it is the
  one the production implementation must have.
- **(c-both) bless both shapes behind an awaitable-normalising seam** (keep `service_decide`
  forever). Rejected: the two shapes differ in *meaning* (who owns time), not just in marker, so a
  normaliser must also invent a `now` — the thing being rejected. Two blessed shapes is a permanent
  adapter in the mutating path and a contract that names no single truth; the wave-1 route already
  refused to normalise for exactly this reason.
- **(d) widen §4's `ApprovalsService` protocol with `decide`** (QA's wave-1 "natural answer",
  §8.3's recorded temptation). §4 is the Tool Manager's seam and the Tool Manager never decides;
  QA B1 is the recorded cost of a surface demanding protocol methods its contract never granted.
  §4 gains the closure paragraph instead (see below).

**Version: v1.2.0, MINOR — defended.** The consumer-facing surfaces (§4 protocol, OpenAPI) are
byte-unchanged; §6.2's only production caller could not call the old shape (the 501), so no working
consumer exists for a MAJOR bump to protect; the in-repo callers of the old fake shape are
enumerated (19 call sites + 1 harness line) and migrated in-wave. Full defense in the C4 changelog.

### R7.1 Migration deltas (verbatim; ordering rule in the C4 changelog — atomic set first, route deletion after)

**Parcel 1 — QA** (`tests/fakes/fake_approvals.py` + 19 frozen call sites listed in the C4
changelog). Replacement method, byte-exact:

```python
    async def decide(
        self,
        approval_id: str,
        decision: Literal["approve", "refuse"],
        reason: str | None = None,
    ) -> Approval | StateConflict | None:
        """C4 §6.2 (v1.2.0, ruling R7) — awaitable; the service reads its OWN
        injected clock, so ``now`` is no longer a parameter (clock ownership,
        C4 §6). ``pending`` + clock < ``expires_at`` → transition, set
        ``decided_at`` from the clock, ``decided_by="owner"``, return the row.
        ``pending`` + clock >= ``expires_at`` → transition to ``expired`` first,
        then ``state_conflict(current_status="expired")``. Any other status →
        ``state_conflict`` with it. Unknown id → ``None`` (HTTP 404)."""
        row = self.approvals.get(approval_id)
        if row is None:
            return None

        if row.status == ApprovalStatus.PENDING:
            now = self.clock.now()
            if now >= from_iso(row.expires_at):
                row.status = ApprovalStatus.EXPIRED
                return self._conflict(row)
            row.status = (
                ApprovalStatus.APPROVED
                if decision == "approve"
                else ApprovalStatus.REFUSED
            )
            row.decided_at = to_iso(now)
            row.decided_by = "owner"
            row.decision_reason = reason
            return row

        return self._conflict(row)
```

Call-site rule: `X.decide(a, d, r, <clock>.now())` → `await X.decide(a, d, r)` (every enclosing
test is already `async def`). Module docstring: the first "deliberate design notes" bullet now
applies to `sweep` only; `decide`'s bullet states the v1.2.0 shape and cites the clock-ownership
paragraph.

**Parcel 2 — wiring engineer.**

*`sunil/core/approvals/service.py`: NO CHANGE.* `DatabaseApprovalsService.decide`
(`service.py:446-526`) already implements the ruled shape.

*Atomic-set test edits (land with parcel 1):*

`tests/unit/approvals/harness.py:63`:

```python
        return self.service.decide(approval_id, decision, reason, self.clock.now())
```
→
```python
        return await self.service.decide(approval_id, decision, reason)
```

`tests/unit/approvals/test_mounted_surface.py:259-281` — delete
`test_the_mounted_decision_names_the_gap_when_the_seam_has_no_service_decide` (the scenario is now
non-conformant-by-contract, and its 501 assertion goes red the moment parcel 1 lands) and replace
with:

```python
async def test_the_mounted_decision_runs_on_the_fake_wired_app() -> None:
    """C4 v1.2.0 (ruling R7): the fake's `decide` is the awaitable,
    service-clocked form, so the bootable (fake-wired) configuration's decision
    path answers the contract's codes — the coverage gap `integration-w1.md`
    §8.3 recorded is closed. The row is parked INTO the fake because on a
    fake-wired app the fake is the decision store while the reads are the
    database read model (a test-only split; §5 item 3)."""
    async with mounted() as (client, _app, _engine):
        fake = _app_service(_app)
        parked = await fake.park(park_request())

        decided = await client.post(
            f"/api/v1/approvals/{parked.approval_id}/decision",
            json={"decision": "approve"},
            headers=WEB_HEADERS,
        )

        assert decided.status_code == 200, decided.text
        assert decided.json()["status"] == "approved"
```

*Route deletion (any time after the atomic set is in the integration tree)* — in
`sunil/api/routes/approvals.py`: delete `service_decide` (:291-318), `DECISION_SEAM_MISSING` and
its comment block (:321-333), the unused `from inspect import iscoroutinefunction` (:60), and the
module docstring's `| no service-layer decide at all | 501 ... |` table row (:41); in
`decide_approval` replace

```python
        service = get_approvals_service(request)
        decide = service_decide(service)
        if decide is None:
            return JSONResponse(
                status_code=501, content=DECISION_SEAM_MISSING, headers=NOSNIFF
            )
        result = await decide(approval_id, body.decision, body.reason)
```
with
```python
        service = get_approvals_service(request)
        result = await service.decide(approval_id, body.decision, body.reason)
```

A wired seam whose `decide` is not awaitable is henceforth a wiring defect — the same 500 class as
`app.state.approvals_service` unset.

*Same-wave follow-up owed (small):* implement §3 reconciliation rule 4 in
`DatabaseApprovalsService.reconcile_on_startup` (+ `ReconciliationReport` bucket + test) — see
R7.2.

### R7.2 The two v1.1.x verification points the wave surfaced (deliverable 4)

- **Effect hooks — blessed AND specified.** C4 §3 named the approve/refuse effects with no actor;
  the route's optional-with-logged-warning treatment is now the contract's (§3 "Post-decision
  hooks"): conventional names `finalise_refusal(approval_id)` / `scheduler.schedule(approval_id)`,
  optional-by-wiring, warning names the unrun effect, a hook failure logs and the 200 stands (the
  CAS committed; the owner's decision must not be reported failed). Blessing "warn and stand"
  without a recovery path would be a data-loss shrug, so **reconciliation rule 4** was added in the
  same ruling: `refused`/`expired` + unfinalised task → finalise with the matching kind. Rule 4
  also closes a second window found while verifying: the decide-time lazy `pending → expired`
  (`service.py:509-520`) audits but never finalises the task, and only `sweep` calls
  `_finalise_expired_tasks` (`service.py:577`) — an expired row is invisible to the sweep's
  pending/approved WHERE clauses, so without rule 4 that task stays unfinalised forever.
  Implementation is the named same-wave engineer follow-up above.
- **Read-model precedent — recorded normative** (C4 §4 "The protocol is closed; reads are a read
  model"): list/get stay OFF the service protocol permanently; §6.5 is a listing law binding the
  fake and the read model alike; convenience reads on a service are delegation, not contract;
  `continuation` exclusion is structural through the one column list. No future lane may satisfy a
  route by widening the protocol.

**R7 boundaries:** files touched — `docs/contracts/C4-approvals.md` and this file, on branch
`task/S2-rulings`. No code, no tests, no ADRs; appliers are named per parcel above.

---

## Boundaries observed

Files touched: `docs/decisions/ADR-008-*.md`, `docs/ARCHITECTURE_V2.md`, `docs/THREAT_MODEL.md`,
`docs/tasks/P0-contracts.md`, `docs/tasks/S-D-web.md` (one dated closure note), this file, and one
ruling comment in `config/agents.yaml`. No application code, no tests, and none of the backend
lane's concurrent files (`api/routes/approvals.py`, `.env.example`, tests). Rulings that require
code (R2 steps 1–3, R3's lane move, R1's startup warning) name wave-2's wiring round as applier.
