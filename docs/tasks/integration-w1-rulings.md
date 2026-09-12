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
| R7.2Δ | S2-wiring §7 item 4 — engineer delta for C4 §3 rule 4 + the decide-time lazy-expiry finalisation gap (wiring round item 2, 2026-09-12) | This file (applier: backend/wiring engineer; no contract movement — C4 v1.2.0 already carries rule 4) |
| R8 | S2-wiring §7.5 — parked turn's C5 envelope carries `approval_id=""` under real wiring (wiring round item 1, 2026-09-12) | **C1 v1.2.0** (§2 `ApprovalRef` + `ToolResult.approval`, §2.1 step-3/step-7, §6.4 tests 4/5/10, changelog) + this file's engineer delta |
| R9 | S2-C §1 — direct pgvector over Mem0 (round-2 ratification batch, 2026-09-12, branch `task/integration-w2r2`) | **ADR-030 Amendment 2** (ratified) + **C3 v1.1.1** descriptive prose |
| R10 | S2-C §7.3 — embedding calls bypass `llm_calls`; C3 §2 promised audit frozen C2 cannot provide | **C3 v1.1.1** (§2 bullet truth-fix + changelog) + this file (C2 v2.0.0 candidate register — C2 untouched until it moves, R4 precedent) |
| R11 | S2-F §5.5 — `AgentResult.kind` has no `engine_failed`; new members are silent success in `turn.py` | This file (folding blessed; the future parcel specified; exhaustiveness-guard follow-up named) |
| R12 | S2-C §7.5 — `projects` TABLE vs `config/projects.yaml` name collision | This file (document-and-keep + the one-namespace bridge rule) |
| R13 | S2-C §7.6 — `EntityResolver` built-but-unwired | This file (wiring delta + owning round) |
| R14 | S2-F §5.3 + S2-E §7.1 — `SUNIL_OPENHANDS_BASE_URL`, `openhands` named host, n8n MCP path | **ADR-033 Amendment 1** + **ARCHITECTURE_V2 §5/§4** dated corrections |
| R15 | Round-2 owed-sections sweep (S2-C §7, S2-E §7 + §4 follow-up, S2-F §5) | This file (disposition table) + **THREAT_MODEL §9** (DC-21 + dated closure block) |

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

## R8 — the park exit's approval reference is a typed C1 field, never `data` (S2-wiring §7.5, 2026-09-12)

**Defect, chain verified in the merged tree** (`origin/task/integration-w2r1`): the real
`ToolManager` returns `data=None` on every error result (`manager.py::_error`, :603-617) —
**conformant** with C1 §2's frozen rule (`data: dict | None — None when ok=False`) — and the minted
approval id reaches only the attempt-audit row (`manager.py:287`, and `:492` where
`_parked_in_one_transaction` literally discards the returned `ParkedApproval` as `_parked`). The PM
agent reads `tool_result.data.get("approval_id"/"expires_at")` (`agents/project_manager/agent.py:174,
182-183`) → always `None` → `AgentTurnResult.approval_id=None` (`agent.py:88-89`) → the orchestrator
mints the poison: `approval_id=result.approval_id or ""` (`core/orchestrator/turn.py:430-431`, and
`:422`'s `"approval": "none"` trace detail — the live evidence in §7.5). The integration double
(`tests/integration/tool_manager_double.py:141-151`) invented `data={"approval_id": …,
"expires_at": …}` behind a comment that is false twice over — "which the real manager does too
(C1 §4's error results may carry data)": the real manager never does, and C1 §2 forbids it — which
is why every integration test was green against behaviour the shipped code does not have.

**Root cause is the CONTRACT's own gap, which the double papered over with a lie and the real
manager honoured into a defect.** C1 §2.1's park bullet obligated the orchestrator to surface an id
("the approval id travels in `ParkedApproval` and is surfaced by the orchestrator") while providing
no channel: `ParkedApproval` returns to the *manager*, and the only value the orchestrator receives
is a `ToolResult` whose `data` the same contract requires to be `None`. Two implementations resolved
the contradiction in opposite directions; the tests followed the lying one.

**Ruling — candidate (a): a typed field, C1 v1.2.0 (instrumented in
`docs/contracts/C1-tool-adapter.md`, this commit).** New frozen dataclass
`ApprovalRef(approval_id: str, expires_at: str)` in `core/tool_framework/base.py`, and
`ToolResult.approval: ApprovalRef | None = None` with the invariant **non-None IFF
`error_kind == "approval_required"`**, populated by both park exits by verbatim copy from
`ParkedApproval` — the same one-composer discipline the pipeline already applies to `ParkContext` —
and **cleared at step 7** on adapter-returned results (only the park exit mints it). MINOR by C1's
own change policy (additive optional field); §2.1 step 3 and step 7 amended, §6.4 tests 4/5
extended, new test 10 (forged-`approval` clearing probe), changelog entry with the MINOR defense.

**Grounds.** (1) *It is metadata the manager mints, not adapter output* — the honest home is a
manager-owned typed field, exactly like `meta`, which the manager already re-stamps because "an
adapter must not describe itself onto the audit trail" (`manager.py::_normalise`). (2) *§3's
untrusted-data posture weighs decisively against the `data` channel*: every `ToolResult.data` is
contract-labelled adapter-attributed untrusted output — it is what gets rendered into the LLM's
delimited external-tool-output block (`agent.py::_as_untrusted`) and what the MCP strip/cap treats.
An approval id in `data` transits that pipeline as if the adapter said it, and the fact being
transported is the one the owner's decision UI navigates by (design decision D9: the dashboard
links a parked turn to its approval card by this id). A channel whose trust label is "whatever the
tool said" must not carry the pointer that steers which approval the owner decides. (3) *The typed
field turns this whole defect class into a loud failure*: `data.get("approval_id")` returned `None`
silently for an entire wave; `result.approval.approval_id` on a result without the field is an
`AttributeError` on first contact. (4) The step-7 clearing rule closes the field's own spoof
channel before it opens: `dataclasses.replace` in `_normalise` would otherwise preserve an
adapter-forged `approval`, letting a hostile adapter point the owner's decision UI at an approval
its call never parked.

**Rejected alternatives, by name:**

- **(b) keep it in `data` and make the real manager populate it** (what the double faked). Changes
  a frozen field's semantics (`data: None when ok=False`) — MAJOR by C1's change policy plus a new
  ADR, to codify a comment that misquoted §4; puts a manager-minted, UI-load-bearing fact into the
  §3 channel (ground 2); is unfixable against forgery, because `data` is definitionally the
  adapter's and the manager cannot stamp provenance onto keys inside it; and forces
  "except approval_required" carve-outs into every consumer that treats error-result `data` as
  absent (the agent's own `"data": None if not tool_result.ok else data` line).
- **(c) the orchestrator re-reads the reference from the audited attempt row** (§7.5's candidate
  (b), the "from the audited record" analogy). Fails on fact: `ToolCallAttempt` carries
  `approval_id` but **no `expires_at`**, so the C5 ref is unassemblable from the audit row alone —
  the agent would need a second read through a C4 read-model seam it does not hold, two
  cross-store reads to recover a value the manager held in a local variable one frame down. Fails
  on semantics: `_decision_of`'s precedent exists so the *agent* cannot vouch for a decision the
  *engine* made — audit outranks the agent's claim. Here the manager IS the authority and the
  `ToolResult` is the manager's own authored record; the typed field is "from the authoritative
  record". And fails on correctness: a latest-attempt scan keyed on tool+operation
  (`agent.py:244-245`'s pattern) links the WRONG approval the first time a plan calls the same
  operation twice.
- **(d) fix nothing in C1; delete the double and let the defect surface.** The double's own header
  says it dies when Stream A lands, and Stream A has landed — but deletion alone just moves the
  green suite to red without ruling where the id lives, and the turn still cannot surface it.
  Retirement is owed *in addition* (below), not instead.

### R8.1 Engineer delta (applier: backend/spine engineer — ONE atomic set; each piece alone goes red or changes nothing)

**1. `sunil/core/tool_framework/base.py`** — after `ToolResultMeta`, add; and append the defaulted
field to `ToolResult` (last position — it is the only defaulted field):

```python
@dataclass(frozen=True)
class ApprovalRef:
    """The park exit's approval reference (C1 v1.2.0, ruling R8): copied VERBATIM
    from C4's ParkedApproval by the Tool Manager at the park exit — metadata the
    MANAGER mints, deliberately not carried in `data` (§3's channel is
    adapter-attributed untrusted output; this is not that)."""

    approval_id: str
    expires_at: str
```

```python
    approval: ApprovalRef | None = None
    # C1 v1.2.0 (ruling R8): non-None IFF error_kind == "approval_required" —
    # the reference the orchestrator surfaces into C5's `outcome=parked`. Only
    # the manager's park exit mints it; step 7 clears any adapter-set value.
```

**2. `sunil/core/tool_framework/manager.py`** — four touches:

- `_error` (:603) gains keyword-only `approval_ref: ApprovalRef | None = None`, passed through as
  `approval=approval_ref` in the `ToolResult(...)` constructor.
- `_early_exit` (:523) gains keyword-only `approval_ref: ApprovalRef | None = None`, forwarded to
  its `_error` call (:565).
- The plain park exit (:273-288): add to the existing `_early_exit` call
  `approval_ref=ApprovalRef(approval_id=parked.approval_id, expires_at=parked.expires_at)`
  (alongside the existing `approval_id=parked.approval_id` audit-row argument).
- `_parked_in_one_transaction` (:492): rename the discarded `_parked` to `parked` and build the
  result as
  `self._error(..., approval_ref=ApprovalRef(approval_id=parked.approval_id, expires_at=parked.expires_at))`.
- `_normalise` (:597-601): the `replace(...)` gains `approval=None` — step 7's clearing rule
  (v1.2.0). Park exits never pass through `_normalise`, so the field survives exactly where it was
  minted.

**3. `sunil/agents/project_manager/agent.py:174-186`** — read the typed field, stop mining `data`:

```python
        ref = tool_result.approval
        return {
            "step_id": step.id,
            "tool": step.tool,
            "operation": step.operation,
            "ok": tool_result.ok,
            "error_kind": tool_result.error_kind,
            "permission_decision": _decision_of(ctx, step),
            "approval_id": ref.approval_id if ref is not None else None,
            "expires_at": ref.expires_at if ref is not None else None,
            "summary": park_context.summary,
            "data": tool_result.data if tool_result.ok else None,
        }
```

(`agent.py:88-89` and `turn.py:430-431` need no edit: the dict keys keep their names, now
truthfully populated. `turn.py`'s `or ""` becomes unreachable-by-contract — the §6.4 test-4 pin
plus the conformance test below are what make it so; leave it as type narrowing.)

**4. `tests/integration/tool_manager_double.py`** — the double stops lying: delete lines 141-151
(the wrapping `ToolResult(...)` and the false comment) and replace the park exit with

```python
                result = await self._exit(
                    agent_id, tool, operation, ToolErrorKind.APPROVAL_REQUIRED,
                    f"parked as {parked.approval_id}", decision, canonical, started,
                    adapter=adapter, approval_id=parked.approval_id,
                )
                return replace(
                    result,
                    approval=ApprovalRef(
                        approval_id=parked.approval_id, expires_at=parked.expires_at
                    ),
                )
```

with `from dataclasses import replace` and `ApprovalRef` added to the imports. Every
`test_governed_turn.py` assertion (:168, :179, :195-201) keeps passing — now against the shape the
real manager actually has.

**5. Conformance assertion (the anti-drift device) — new `tests/integration/test_double_conformance.py`.**
The double may exist only while it matches the real chokepoint field-for-field; if this test goes
red, fix the DOUBLE (or retire it), never the expectation:

```python
"""Ruling R8: the integration double must match the real ToolManager on every
C1-observable field a consumer may branch on. The wave-2 defect existed because
the double asserted a park shape the real manager never had — this file makes
that drift a red test instead of a green lie."""

from tests.fakes.fake_tool_adapter import FakeToolAdapter
from tests.fakes.fake_hooks import FakePermissionHook, RecordingAuditHook
from tests.fakes.fake_approvals import FakeApprovalsService
from tests.integration.tool_manager_double import ToolManagerDouble
from sunil.core.tool_framework.base import ParkContext, TraceContext
from sunil.core.tool_framework.manager import ToolManager


async def _park_result(manager_cls):
    hook = FakePermissionHook()
    hook.grant("agent-1", "fake_tool", "write_item", "ask_user")
    approvals = FakeApprovalsService()
    manager = manager_cls([FakeToolAdapter()], hook, approvals, RecordingAuditHook())
    result = await manager.execute(
        "agent-1", "fake_tool", "write_item", {"key": "demo", "value": "v"},
        trace=TraceContext(request_id="req-1", task_id="task-1", conversation_id="conv-1"),
        park_context=ParkContext(
            continuation={"plan_id": "plan-1", "cursor": 0},
            summary="fake_tool.write_item requires approval",
        ),
    )
    return result, approvals


async def test_double_park_result_matches_the_real_manager() -> None:
    real, real_approvals = await _park_result(ToolManager)
    double, double_approvals = await _park_result(ToolManagerDouble)

    # Fields consumers branch on: identical values (duration_ms is measured,
    # error_message is prose — both contract-excluded from branching, §4).
    assert double.ok == real.ok
    assert double.data == real.data == None  # noqa: E711 - the frozen §2 rule, asserted literally
    assert double.error_kind == real.error_kind == "approval_required"
    assert double.meta.adapter_kind == real.meta.adapter_kind
    assert double.meta.server_id == real.meta.server_id

    # The approval ref: same SHAPE, and each links to a row its own store parked.
    for result, approvals in ((real, real_approvals), (double, double_approvals)):
        assert result.approval is not None
        assert result.approval.approval_id in approvals.parked
        row = approvals.approvals[result.approval.approval_id]
        assert result.approval.expires_at == row.expires_at
```

**6. Contract-test transcription (applier: QA — frozen-suite diff, lands immediately after the
atomic set):** `tests/contracts/test_c1_tool_adapter.py` — test 4 gains the two REQUIRED v1.2.0
equality assertions (`data is None`; `approval ==` the fake's stored id/expiry), test 5 gains
`approval is None` on the `approval_invalid` result, and new test 10 transcribes §6.4's
forged-approval clearing probe verbatim.

**Landing order (why atomic):** correcting the double without the field reds
`test_governed_turn.py:168`; adding the field without the agent read changes nothing observable;
the agent read without the manager populating it re-mints `""`. Pieces 1-5 are one commit; piece 6
follows it.

**Same-wave follow-up owed (spine/QA lanes, named — not this atomic set):** retire the double per
its own charter ("When Stream A lands, this file is deleted") — `conftest.py:95-101` swaps
`ToolManagerDouble(...)` for the real `ToolManager(...)` (same constructor shape, the swap the
docstring promised) and `test_double_conformance.py` dies with the double. Deferred out of the
atomic set only because the integration suite is under two concurrent reviews this round;
correction-plus-conformance makes the interim state honest.

**R8 boundaries:** files touched by THIS ruling — `docs/contracts/C1-tool-adapter.md` (v1.2.0) and
this file, branch `task/S2-rulings`. No code; appliers named per parcel above.

---

## R7.2Δ — engineer delta: reconciliation rule 4 + the decide-time lazy-expiry finalisation (wiring round item 2, 2026-09-12)

Completes the R7.2 bullet above and S2-wiring §7 item 4. **No contract movement** — C4 v1.2.0 §3
already carries rule 4 verbatim; this is the implementation order for
`sunil/core/approvals/service.py` plus the tests that pin it. Applier: backend/wiring engineer.
The gap, restated from the verification that produced rule 4: the decide-time lazy
`pending → expired` (`service.py:509-520`, audit cause `decide_past_ttl`) audits but never
finalises the task, and only `sweep()` calls `_finalise_expired_tasks` (`service.py:577`) — an
`expired` row can never again match the sweep's `status=pending` / `status=approved` WHERE clauses,
so without these two deltas that task stays unfinalised forever.

**Delta 1 — `ReconciliationReport` gains the rule-4 bucket** (`service.py:146-165`):
`__slots__ = ("rescheduled", "expired", "interrupted", "finalised")`; `__init__` gains
`self.finalised: list[str] = []`; `total` adds `+ len(self.finalised)`; `__repr__` includes it;
docstring "three rules" → "four rules".

**Delta 2 — a rule-4 audit kind** (`service.py`, beside :90-92):
`AUDIT_TASK_RECONCILED = "task_finalisation_reconciled"`. Deliberately NOT `AUDIT_RECONCILED`
(`continuation_reconciled`) — nothing about a refused/expired row is a continuation event, and C4
§3 rule 3 names that kind for the consumed case specifically.

**Delta 3 — rule 4 in `reconcile_on_startup`** (`service.py:670-757`): docstring gains the rule-4
line; the existing `engine.connect()` read block (:716-731) gains a third select; a fourth loop
lands after rule 3's:

```python
            terminal = (
                await conn.execute(
                    select(T.c.id, T.c.task_id, T.c.status).where(
                        T.c.status.in_(
                            [
                                ApprovalStatus.REFUSED.value,
                                ApprovalStatus.EXPIRED.value,
                            ]
                        )
                    )
                )
            ).fetchall()
```

```python
        # Rule 4 — refused/expired + unfinalised task → finalise with the
        # matching kind (C4 §3 rule 4, v1.2.0 ruling R7). Closes the two windows
        # the post-decision hooks leave open: a crash (or absent task gateway)
        # after a refuse CAS, and the decide-time lazy `pending → expired`,
        # whose row leaves the sweeper's WHERE clauses before the sweep's
        # finalisation pass can ever see it. Rows rule 2 expired THIS pass are
        # re-seen here with their tasks already finalised, so the is_finalised
        # guard skips them — and a rule-2 finalisation that FAILED last boot is
        # retried, which rules 1-3 never did for anything.
        for row in terminal:
            if self.tasks is None or await self.tasks.is_finalised(row.task_id):
                continue
            kind = (
                FAILURE_APPROVAL_REFUSED
                if row.status == ApprovalStatus.REFUSED.value
                else FAILURE_APPROVAL_EXPIRED
            )
            report.finalised.append(row.id)
            await self._finalise(row.task_id, kind)
            await self._audit(
                AUDIT_TASK_RECONCILED,
                row.id,
                {"task_id": row.task_id, "failure_kind": kind},
            )
```

Scan posture, recorded: `terminal` reads every refused/expired row ever, exactly as rule 3 already
reads every consumed row — acceptable at this system's approval volumes (every row cost a human
decision), and if it ever hurts, the fix is one bulk `unfinalised_task_ids()` question on
`TaskGateway` serving all four rules, never a rule-4 special case.

**Delta 4 — `decide`'s lazy expiry finalises after commit** (`service.py:498-526`): condition the
audit on the CAS actually transitioning (`.returning` — today a raced-away UPDATE still writes a
`decide_past_ttl` audit row for a transition that never happened), move the conflict return out of
the transaction, finalise through the same door the sweep uses:

```python
        lazily_expired = False
        async with self.engine.begin() as conn:
            # ... the decided-CAS branch is unchanged ...
            current = (
                await conn.execute(
                    select(T.c.id, T.c.status).where(T.c.id == approval_id)
                )
            ).first()
            if current is None:
                return None
            if current.status == ApprovalStatus.PENDING.value:
                expired_row = (
                    await conn.execute(
                        update(T)
                        .where(
                            T.c.id == approval_id,
                            T.c.status == ApprovalStatus.PENDING.value,
                            T.c.expires_at <= now,
                        )
                        .values(status=ApprovalStatus.EXPIRED.value)
                        .returning(T.c.id)
                    )
                ).first()
                if expired_row is not None:
                    lazily_expired = True
                    await self._audit(
                        AUDIT_EXPIRED, approval_id, {"cause": "decide_past_ttl"}, conn
                    )
                current = (
                    await conn.execute(
                        select(T.c.id, T.c.status).where(T.c.id == approval_id)
                    )
                ).first()
            conflict = self._conflict(current)
        if lazily_expired:
            # This call is the LAST actor guaranteed to see the transition (the
            # row just left the sweeper's WHERE clauses for good), so it owns
            # the finalisation exactly as sweep() owns its own at :577 — after
            # commit, is_finalised-guarded, failure logged-not-raised (the 409
            # must stand; rule 4 retries on the next boot).
            await self._finalise_expired_tasks([approval_id])
        return conflict
```

`decide`'s docstring gains one line naming the finalisation and its after-commit posture. If the
CAS raced away to a concurrent sweep/decide, `lazily_expired` stays False and the winner owns the
finalisation — no double writer, and no more phantom audit row.

**Tests (pin in `tests/unit/approvals/test_reconciliation.py` — the `wired` fixture, `_park`,
`RecordingTasks`, `RecordingAudit` all exist there):**

```python
# --------------------------------------------------------------------------- #
# Rule 4 — refused/expired + unfinalised task → finalised with the matching kind
# --------------------------------------------------------------------------- #
async def test_rule_4_finalises_a_refused_row_whose_hook_never_ran(wired) -> None:
    """park → refuse → crash before finalise_refusal → startup reconciles.
    The decide CAS committed REFUSED; the process died before the post-decision
    hook ran (C4 §3 "Post-decision hooks"). Without rule 4 this task stays open
    for ever — no sweep clause and no other rule can ever see it."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-refused-crash")
    await service.decide(approval_id, "refuse", "no")
    # deliberately NO finalise_refusal(): the crash window under test

    report = await service.reconcile_on_startup()

    assert report.finalised == [approval_id]
    assert tasks.calls == [("task-refused-crash", FAILURE_APPROVAL_REFUSED)]
    assert scheduler.scheduled == []
    assert AUDIT_TASK_RECONCILED in audit.kinds_for(approval_id)


async def test_rule_4_leaves_a_hook_finalised_refusal_alone(wired) -> None:
    """The non-crash case: the hook ran, the task is closed. Rule 4 must be a
    no-op or every clean boot re-finalises history."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-refused-ok")
    await service.decide(approval_id, "refuse")
    await service.finalise_refusal(approval_id)

    report = await service.reconcile_on_startup()

    assert report.finalised == []
    assert len(tasks.calls) == 1
    assert AUDIT_TASK_RECONCILED not in audit.kinds_for(approval_id)


async def test_rule_4_retries_a_finalisation_the_gateway_failed(wired) -> None:
    """expired + unfinalised at boot — the lazy-expiry crash window: the CAS
    committed, the gateway call failed (logged, 409 stood), the process moved
    on. Rule 4 is the retry."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-lazy-crash")
    clock.advance(hours=73)  # past the 72 h TTL
    tasks.fail_next = 1  # see the RecordingTasks delta below
    outcome = await service.decide(approval_id, "approve")

    assert isinstance(outcome, StateConflict)
    assert tasks.calls == []  # the one attempt failed and was swallowed

    report = await service.reconcile_on_startup()

    assert report.finalised == [approval_id]
    assert tasks.calls == [("task-lazy-crash", FAILURE_APPROVAL_EXPIRED)]


# --------------------------------------------------------------------------- #
# The decide-time lazy expiry finalises (sweep parity)
# --------------------------------------------------------------------------- #
async def test_lazy_expiry_at_decide_time_finalises_the_task(wired) -> None:
    """decide's `pending → expired` CAS (cause `decide_past_ttl`) takes the row
    out of the sweeper's pending/approved WHERE clauses for good, so decide owns
    the finalisation exactly as sweep owns its own — no restart required."""
    service, clock, tasks, scheduler, audit = wired
    approval_id = await _park(service, clock, "task-lazy")
    clock.advance(hours=73)  # past the 72 h TTL

    outcome = await service.decide(approval_id, "approve")

    assert isinstance(outcome, StateConflict)
    assert outcome.error.current_status == ApprovalStatus.EXPIRED
    assert tasks.calls == [("task-lazy", FAILURE_APPROVAL_EXPIRED)]
    assert await service.sweep() == 0  # nothing left for the sweep to notice
```

Support deltas in the same test module: import `FAILURE_APPROVAL_REFUSED` and
`AUDIT_TASK_RECONCILED` from `sunil.core.approvals.service`, `StateConflict` from
`sunil.core.approvals.base`; `RecordingTasks` gains the failure valve —
`self.fail_next = 0` in `__init__`, and at the top of `finalise_failed`:
`if self.fail_next: self.fail_next -= 1; raise RuntimeError("task gateway down")`.
The existing suite stays green as-is — verified against each test: rule 2's freshly expired rows
reach rule 4 with tasks already finalised (guard skips; `test_reconciliation_is_idempotent`'s
totals hold at 2/0), and `test_refusal_finalises_the_task_as_refused` runs the hook so rule 4
never fires there.

**R7.2Δ boundaries:** this file only, branch `task/S2-rulings`. Code deltas above are the backend
lane's to land (service.py + one lane-owned test module); no frozen suite, no contract file, no
route moves.

---

## R9 — direct pgvector over Mem0: RATIFIED (round-2 ratification batch, 2026-09-12)

**Ruling: ratified as ADR-030 Amendment 2** (the normative instrument — see
`docs/decisions/ADR-030-integrate-open-source-components.md`), with C3's descriptive vendor prose
corrected in the same batch (v1.1.1). The component decision moves; the principle — a replaceable
engine behind the frozen C3 seam — is what survives, and Stream C's implementation *strengthens*
it: `SUNIL_MEMORY_PROVIDER=mem0` stays selectable and resolves to a loud `SeamUnavailable` naming
the unbuilt module, never a silent fallback.

**Why ratify rather than order Mem0:** the lane's grounds are conformance facts about C3's own
frozen text, not preference — (1) Mem0's LLM write path re-classifies and rewrites stored facts,
which §2 forbids verbatim and which cannot satisfy §4a's exact lattice arithmetic repeatably in a
contract test; (2) no `privacy` column in its schema — the field §4a turns on; (3) keyless machine
⇒ the parity proof would be unrunnable, i.e. an ordered Mem0 build would land unverifiable.
Ordering Mem0 would therefore have bought a vendor whose contract-relevant behaviour must all be
re-implemented in the adapter around it. **Rejected alternatives** (argued in the Amendment): order
Mem0 anyway; a standalone ADR-037 (fragments the component register); deleting `mem0` from the
selectable set (erases the replaceability evidence).

**Instrument:** ADR-030 Amendment 2 + C3 v1.1.1 + the `ARCHITECTURE_V2.md` §5
`SUNIL_MEMORY_PROVIDER` row (all this commit). No code moves; the code already implements the
ratified state.

---

## R10 — the embedding audit gap: C3 §2 corrected to the truth; `embed()` registered as the C2 v2.0.0 candidate

**The gap, verified:** C3 §2's embeddings bullet promised "routing, budgets and audit" from the C2
gateway. Routing and budgets hold (the `GatewayEmbedder` posts to the LiteLLM gateway on a virtual
key; the gateway logs spend). Audit does **not**: SUNIL's `llm_calls` rows are written by the C2
provider path, and the frozen `LLMProvider` protocol (`C2-model-provider.md` §2, v1.0.1) has
exactly `complete()` and `stream()` — no `embed()`. A contract may not promise what no conforming
implementation can do, and a memory lane may not widen C2 on its way past (protocol changes are
MAJOR + ADR by C2's own change policy).

**Ruling, two halves:**

1. **C3 v1.1.1 (this commit)** — §2's bullet now states what is true: embeddings inherit routing
   and budgets via the gateway transport; they do not appear in `llm_calls`; the gateway spend log
   is the only per-call record of embedding egress until the candidate lands. PATCH defended in
   the C3 changelog (no signature/semantics movement; the promise was unimplementable).
2. **C2 v2.0.0 candidate, registered here** (R4 precedent: the contract file moves only when the
   change moves): `async def embed(self, request: EmbeddingRequest) -> EmbeddingResult` on
   `LLMProvider`, closed models, `agent_id`/`request_id`/`privacy_class` carried exactly as
   `CompletionRequest` does, `llm_calls` row written by the same audited path as `complete()`.
   MAJOR by C2's change policy (protocol change) ⇒ **needs its own ADR** at landing time.
   **Owning round: Stream B's next gateway round** (first round that holds an embedding
   credential, so the live leg is provable — the same reason Stream C could not prove
   `GatewayEmbedder` live).

**Coupling rule (architect direction):** the `SUNIL_MEMORY_EMBEDDER` default stays `hashing` until
**both** an embedding key exists **and** the C2 v2 audit lands. Semantic recall by default must not
precede embedding egress appearing on the audit spine — flipping the default is the moment memory
content routinely leaves the process, and "the gateway's spend log" is a billing record, not
SUNIL's audit trail.

**Rejected alternative:** leave C3 §2 as written and treat the gap as an implementation TODO.
Rejected because a frozen contract stating false behaviour is exactly the drift class R8 just
closed (the double that "papered over the contract's gap with a lie"); the register-and-correct
pattern keeps every frozen document true at every commit.

---

## R11 — engine failures keep folding to `kind="tool_failed"`; `engine_failed` is specified-but-unscheduled

**Facts, verified in the tree:** `core/agent_framework/base.py:80` pins
`AgentResult.kind: Literal["ok", "parked", "tool_failed", "provider_error"]`;
`core/orchestrator/turn.py:275-280` dispatches `parked`/`tool_failed`/`provider_error` and treats
anything else as success — so a new enum member added without a `turn.py` change is **silent
success**, exactly as Stream F reported. C5's `failure.kind` is likewise a closed enumerated set
(`provider_error`, `tool_failed`, `plan_rejected`, `unknown_project`, plus the v1.1 approval
kinds), so a distinct `engine_failed` is not a two-file change: it is base.py + turn.py + a C5
MINOR (failure kind + fake behaviour + frozen-suite diff) + whatever renders failures in the web
app. Four surfaces, one atomic parcel.

**Ruling: BLESS the current folding.** It is honest at every layer that matters:

- the C5 surface says "a governed step failed", which is true at the granularity its consumers act
  on today (no consumer exists that must *branch* engine-vs-tool at the envelope);
- `tool_error_kind` carries the honest C1 §4 kind (`upstream_error`/`transport_error`/`timeout`/
  `invalid_params`) — the folding never launders the cause;
- the engine's own `failure_kind` string is preserved unmapped in `tool_details` — full forensic
  recovery from the audit trail.

**The trigger that reopens this** (recorded so it is inherited, not rediscovered): the first
consumer that must branch on engine-vs-tool at the C5 surface — e.g. a dashboard "developer engine
down" banner, or a retry policy treating engine failures differently. At that trigger,
`engine_failed` lands as ONE atomic parcel (base.py Literal + turn.py mapping + C5 MINOR with
changelog + fake + frozen-suite diff), owned by the round that owns the consumer. Not scheduled
now — a kind nobody branches on is taxonomy, not information.

**Hardening owed (spine owner, next spine-touching round, no contract movement):** `turn.py`'s
kind dispatch gains an exhaustiveness guard (narrow the literal per branch, `typing.assert_never`
in the final else) so any future `AgentResult.kind` member is a type-check failure AND a loud
runtime error — never silent success. This retires the hazard class Stream F discovered, rather
than just this instance of it.

**Rejected alternative:** add `engine_failed` now. Rejected as YAGNI with real cost: a C5 contract
movement + frozen-suite diff for a distinction no consumer reads, on an agent whose engine is not
yet live (S2-F: vendor mapping `unverified-until-first-live-boot`).

---

## R12 — `projects` the TABLE and `projects.yaml` the REGISTRY: document-and-keep, one key namespace (normative)

**Ruling: no rename.** The entity table stays `projects`; the ADR-016 registry stays
`config/projects.yaml`. Grounds: C3 §3 names the entity trio (`clients`, `projects`, `people`) in
a frozen contract; the trio is symmetric and a rename to `project_entities` breaks the symmetry or
forces two more renames nothing motivates; migration `0005` has landed and a rename buys a
migration + code churn for what is a *prose* ambiguity. The two things are genuinely different
kinds: the registry is **operator-mounted configuration** (which repositories SUNIL may reach —
`owner/repo` deliberately lives in config so no plan and no runtime write can choose a repository,
M1 T-16), the table is **runtime data** (entities SUNIL remembers facts about).

**The bridge rule (normative — this is what actually prevents cross-queries going wrong):**

1. **One key namespace.** `projects.key` (the entity table's unique human key) and the registry's
   `project_key` denote the same engagement when equal: `MemoryScope(kind="project", id="pda")`
   and a plan's `project_key: "pda"` MUST refer to the same project. No lane may mint a table
   `key` that collides with a registry key while meaning something else.
2. **Prose discipline.** Docs and code comments say "the `projects` **entity table**" vs "the
   **project registry** (`config/projects.yaml`)" — never bare "projects" where both are in scope.
3. **Materialisation direction:** registry → table, lazily, on first **write**. When the memory
   service resolves a `kind="project"` scope whose id is unknown to the table but IS a registry
   key, a project entity row is upserted from the registry entry (`upsert_entity` exists and is
   idempotent on `key`) and resolution proceeds; **recall never creates rows** (a read must not
   mutate — the same posture as the TTL filter). An id in neither place stays `MemoryScopeError`.
   This is the R13 wiring round's to implement, spec'd here so the two rulings compose.

**Rejected alternatives:** rename to `project_entities` (lexical fix for a semantic question;
breaks C3 §3 naming and trio symmetry; migration churn); merge the registry into the table
(reverses ADR-016's mounted-config law and would make tool reach — `owner/repo` — runtime-mutable
data, a governance regression the config placement exists to prevent).

---

## R13 — `EntityResolver` wiring delta (applier: backend/integration lane, next wiring round — w2r3)

Stream C built and tested `EntityResolver` (`core/memory/entities.py:52` —
`__init__(engine)`, idempotent `resolve(scope) -> MemoryScope`) but did not wire it:
`MemoryService.__init__` was pinned "unchanged in shape" by their brief. This ruling IS the
shape-change authorisation. The delta, exact:

1. **`core/memory/service.py`** — `MemoryService.__init__` gains keyword-only
   `resolver: EntityResolver | None = None` (default preserves every existing call site and the
   fake-wired app).
2. **`recall`**: resolution runs FIRST, **inside** the existing `asyncio.timeout(self._budget_s)`
   block (the 800 ms budget covers resolve + vendor — two sequential DB round-trips must not
   stack two budgets). Error mapping is already designed into the resolver:
   `MemoryUnavailableError` (entity schema unreadable) → the existing `degraded=True,
   reason="unavailable"` path; `TimeoutError` → `reason="budget_exceeded"`;
   **`MemoryScopeError` propagates** — a caller bug surfaces, it never degrades (C3 §3/§4).
3. **`write`**: resolve BEFORE the audit row is minted — the audit sink then records the
   **resolved** scope (the id the provider actually files under; lineage must name the real
   filing), and a write that cannot resolve writes no audit row for a memory that never happened.
   `MemoryScopeError` and `MemoryUnavailableError` both surface on write (a lost write must be
   visible — C3 §4).
4. **`api/wiring.py`** — the `MemoryService` construction site passes
   `resolver=EntityResolver(engine)` whenever the provider resolution had an engine (the
   `pgvector` branch already holds it); fake-wired composition passes none, keeping the frozen C3
   contract suite untouched.
5. **R12 rule 3** (registry → table lazy upsert on write-path resolution) lands in the same
   parcel, in the service — not in the resolver, whose single job stays "key → row id".
6. **Tests owed with the parcel** (lane-owned, not the frozen suite): project-scope recall
   resolves a `key` to its row id and filters correctly; unknown key raises `MemoryScopeError`
   through `write` and through `recall`; entity-schema outage degrades recall
   (`reason="unavailable"`) and surfaces on write; the write-path audit row carries the resolved
   scope; registry-key write-path upsert creates the entity once (idempotent on `key`).

**Rejected alternative:** wire the resolver inside `PgVectorMemoryProvider`. Rejected by C3 §3's
own text — resolution belongs to the *service*, before any vendor call, so the provider only ever
sees resolved ids and `MemoryScopeError` can never depend on which engine is selected.

---

## R14 — `SUNIL_OPENHANDS_BASE_URL`, the `openhands` named host, and the n8n MCP workflow path

**Instrument: ADR-033 Amendment 1** (dated, in the ADR — the addition its Decision paragraph
anticipated by name) **+ the `ARCHITECTURE_V2.md` §5/§4 dated corrections** (this commit). One-line
summary: named-host set + `"openhands"`; governed field `SUNIL_OPENHANDS_BASE_URL` default
`http://localhost:3400` (ADR-032 pair `127.0.0.1:3400→3000`; in-network `http://openhands:3000`),
validator loopback ∨ `openhands`, mechanism `_NAMED_HOSTS` + field + validator in `settings.py`;
and `SUNIL_N8N_MCP_BASE_URL`'s default gains the workflow path `/mcp/sunil` (S2-E §7.1 — `/mcp` is
a prefix, answers 404; the validator constrains host, never path, so no rule moves). **Appliers
(code/config half):** integration engineer — `settings.py`, `.env.example:193`, the compose stub's
`http://n8n:5678/mcp` line. The settings field may land ahead of the engine: an unread validated
setting is inert, and enabling the engine itself stays gated on the S2-F §4 runtime ADR (see R15).

---

## R15 — round-2 owed-sections sweep: dispositions

Everything in the three task files' owed/residual sections not already ruled above, each with its
instrument-or-code disposition:

| Source | Item | Disposition |
|---|---|---|
| S2-C §7.1–7.2 | `GatewayEmbedder` live-unproven; `hashing` recall is lexical, not semantic | Recorded, no instrument. Live proof + default flip belong to the first round holding an embedding key, and the flip is **gated by R10's coupling rule** (audit lands first) |
| S2-C §7.4 | `memories` has no reaper — expired rows filtered, never deleted | Code follow-up registered: an expired-row sweep beside the approvals sweeper (same lifespan hook, own cadence), delete-where-`expires_at < now`; never on the recall path (reads must not mutate). No contract movement — C3 binds recall visibility, not storage hygiene. **Owning round: next wiring/housekeeping round (w2r3)** |
| S2-C §7.5 | `projects` table vs registry | **R12** |
| S2-C §7.6 | `EntityResolver` unwired | **R13** |
| S2-C §7.3 | embedding audit gap | **R10** |
| S2-C §7.7 | three out-of-list file touches (autogenerate fence, `main.py` engine pass, `.env.example`) | Accepted scope excursions — each is load-bearing for the migration's safety or the seam's wiring, flagged to the DM in-file. No instrument |
| S2-E §7.1 | MCP base URL must carry `/mcp/sunil` | **R14** (ADR-033 Amendment 1) |
| S2-E §7.2 | `PostUpdateParams` added outside the file list | Accepted excursion — `params_ref` must point at a real `extra="forbid"` model, and the approval card reads these params; reusing the free-form `payload` model would have degraded owner consent. No instrument |
| S2-E §7.3 | stale Compose volumes / `COMPOSE_PROJECT_NAME` | Ops note; recorded in the task file, sufficient. No instrument |
| S2-E §3 | `run_workflow` removed from both config files (never implemented; drift check took the whole tool down); `RunWorkflowParams` left for a proper build | Endorsed — the removal implements ADR-034's drift posture, and the "named actions, not meta-tools" ground is the right consent shape. A future `run_workflow` needs its own named-operation design; no reservation made |
| S2-E §4 follow-up | the `authentication` dropdown is the single ungoverned setting | **THREAT_MODEL §9: DC-21 + dated closure block** (this commit). The "treat as unauthenticated" posture is CLOSED against n8n 2.38.5 as shipped; the audit obligation is registered with an owner and an exposure pre-condition |
| S2-F §5.1 + §5.2 | `permissions.yaml` developer grants; `tools.yaml` `github_mcp.push_branch`/`merge_main` + params models `{project_key, branch, base_branch}` (`extra="forbid"`) | Registered to **the round that wires github_mcp write operations** (w2r3+/V2-D). **Atomicity rule, from S2-E §3's defect class:** operations + adapters/params and the permission rows land TOGETHER — a config row without an adapter is a startup refusal that takes the whole tool down; a grant without an operation is dead config. Today's fail-closed state (layer-4 rejection) is correct and stays |
| S2-F §5.4 | CI port-gate second pass with `--profile dev-agents` | Registered to DevOps; **MUST land before** the compose `openhands` block is uncommented (compose config omits profiled services — verified v5.5.1, S2-F §4) |
| S2-F §5.5 | `AgentResult.kind` | **R11** |
| S2-F §5.6 | `plan_schema.py`: `"fix_and_pr"` joins `NON_TOOL_ACTIONS` | One-line, layer-1 grammar only (layer 4 already accepts the step); no contract movement. **Owning round: next spine/orchestrator round**, so a constrained-decode planner can emit the work order SUNIL code can already build |
| S2-F §4 | enabling the OpenHands engine needs a runtime decision | Confirmed **an ADR, not an edit** — reserved as the next decision number at drafting time (runtime isolation: remote-runtime vs alternatives; third-party-hosted runtime ships client repo contents off-machine ⇒ privacy-class, owner-level, ADR-030's OmniRoute reasoning verbatim). Until then the commented block with `profiles: [dev-agents]` is the ruled end-state, not an unfinished edit |
| S2-F §1 | vendor constants block `unverified-until-first-live-boot` | Recorded; the first-live-boot round owns correcting the constants + their pin test. The two mapping invariants (unmapped lifecycle string raises; report parse fails closed to zero git ops) survive any correction — they are the governed part |

---

**Round-2 ratification batch boundaries (2026-09-12, branch `task/integration-w2r2`):** files
touched — `docs/decisions/ADR-030-*.md` (Amendment 2), `docs/decisions/ADR-033-*.md` (Amendment 1),
`docs/contracts/C3-memory-provider.md` (v1.1.1), `docs/ARCHITECTURE_V2.md` (§4 TB5 row + §5 rows +
dated append), `docs/THREAT_MODEL.md` (§9 DC-21 + dated block), and this file. **No application
code, no tests, no config** — the concurrent integration engineer owns those files this round;
every code/config delta above names its applier and owning round. C2 deliberately untouched (R10
registers the candidate; the contract moves only when `embed()` moves — R4 precedent).

---

## Boundaries observed

Files touched: `docs/decisions/ADR-008-*.md`, `docs/ARCHITECTURE_V2.md`, `docs/THREAT_MODEL.md`,
`docs/tasks/P0-contracts.md`, `docs/tasks/S-D-web.md` (one dated closure note), this file, and one
ruling comment in `config/agents.yaml`. No application code, no tests, and none of the backend
lane's concurrent files (`api/routes/approvals.py`, `.env.example`, tests). Rulings that require
code (R2 steps 1–3, R3's lane move, R1's startup warning) name wave-2's wiring round as applier.

**2026-09-12 wiring-round append (R8 + R7.2Δ, after merging `origin/task/integration-w2r1`):**
files touched — `docs/contracts/C1-tool-adapter.md` (→ v1.2.0) and this file, on
`task/S2-rulings`. Still no application code and no tests; appliers are named per parcel inside
each ruling.
