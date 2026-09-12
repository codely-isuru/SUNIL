# integration-w1-rulings — wave-1 rulings batch (six items)

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

## Boundaries observed

Files touched: `docs/decisions/ADR-008-*.md`, `docs/ARCHITECTURE_V2.md`, `docs/THREAT_MODEL.md`,
`docs/tasks/P0-contracts.md`, `docs/tasks/S-D-web.md` (one dated closure note), this file, and one
ruling comment in `config/agents.yaml`. No application code, no tests, and none of the backend
lane's concurrent files (`api/routes/approvals.py`, `.env.example`, tests). Rulings that require
code (R2 steps 1–3, R3's lane move, R1's startup warning) name wave-2's wiring round as applier.
