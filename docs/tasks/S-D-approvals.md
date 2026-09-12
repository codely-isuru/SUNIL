# S-D — Approvals service + ops reads (Stream D backend)

**Branch:** `task/S-D-approvals` · **Worktree:** `SUNIL-wt/stream-d-be` ·
**Owner:** backend_engineer · **Status:** built, suite green, awaiting review
**Contracts:** [C4 v1.1.0](../contracts/C4-approvals.md) (+ OpenAPI) ·
[C6 v1.0.0](../contracts/C6-ops-reads.md) (+ OpenAPI) ·
`ARCHITECTURE_V2.md` §2 + **§2 Amendment 1** · ADR-031, ADR-035, ADR-036

---

## 1. Scope built

### C4 — the approvals service on a real database

| Behaviour | Where | Graded by |
|---|---|---|
| `park` → `notify` (webhook, plain-text payload, loopback-validated URL) | `core/approvals/service.py`, `core/approvals/notify.py` | `tests/unit/approvals/test_notify.py` |
| `decide` → `Approval` \| `StateConflict` \| `None`, CAS on `status='pending'` | `service.py` | `test_real_service_contract.py`, `test_cas_race.py` |
| `consume` → CAS + binding recompute + grace bound (`SUNIL_APPROVAL_CONSUME_GRACE_HOURS=1`) | `service.py` | `test_real_service_contract.py`, `test_cas_race.py` |
| the transactional consume + attempt-audit seam for the ToolManager | `service.py` | `test_consume_audit_transaction.py` |
| sweeper: expires **pending past TTL** AND **approved past grace** | `service.py::sweep` | `test_real_service_contract.py`, `test_cas_race.py` |
| **the scheduled runner** around it (startup + every 60 s, error-contained) | `core/approvals/sweeper.py` | `test_sweeper.py` |
| startup reconciliation — `consumed` + unfinalised → `failed`/`continuation_interrupted`, **never re-executed** | `service.py::reconcile_on_startup` | `test_reconciliation.py` |
| HTTP routes per the C4 OpenAPI, 404/409 mapping, C4 error envelope | `api/routes/approvals.py` | `test_routes.py` |
| the table + its own Alembic revision (depends on head, distinct filename) | `core/approvals/table.py`, `db/alembic/versions/20260911_1200_d4_approvals_table.py` | `test_migration_matches_table.py` |

### C6 — the three ops-read surfaces (§2 Amendment 1 naming)

| Route | Module | Operations |
|---|---|---|
| `GET /api/v1/tasks`, `/tasks/{task_id}` | `api/routes/tasks.py` | `listTasks`, `getTask` |
| `GET /api/v1/activity` | `api/routes/activity.py` | `getActivity` |
| `GET /api/v1/audit`, `/audit/{request_id}` | `api/routes/audit.py` | `listAuditTurns`, `getAuditTurn` |

Shared read model + the **one** pagination law: `api/routes/ops_read_model.py`.
Graded by `tests/unit/ops/test_c6_ops_reads.py` over `tests/unit/ops/fixture.py`
(the C6 §6 fixture expressed as rows): the lexicographic `task-9`/`task-10` tie,
the exactly-full-final-page cursor, filters-before-pagination, the activity
tri-partition + 20-cap + three-key `latest_detail` projection, the audit
derivations and detail partition, and byte-faithful untrusted fields.

## 2. Deltas applied when C6 v1.0.0 landed

The first pass was written against `V2_DASHBOARD_SPEC.md` §13 before C6 merged on
`V2`. C6 freezes §13's *shapes* verbatim but adds the derivation and pagination
law, so the shapes stood and the behaviour did not. The single `ops.py` was
replaced by the three amendment-named modules plus the shared read model, and
these defects were fixed **against tests written first**:

1. `project_key` is a real `tasks` column (C6 §3, Q2 ruling), not derived from
   `plan_created.detail` — the derivation could not answer for a task with no
   plan event, and was the N+1-on-a-poll C6 §3 rejects.
2. `project_key` filtering moved **before** pagination (C6 §2.1.2). Post-filtering
   a page silently dropped rows a page walk would never return.
3. `order=oldest` reverses both **sort keys** (C6 §2.1.6). Reversing the returned
   page handed back the newest rows on page one under an "oldest" label.
4. `q` is explicitly case-insensitive — `LIKE` folds case on SQLite but not on
   Postgres, so the pre-C6 code would have changed behaviour at deployment.
5. `status` outside the enum is 422, not an empty list.
6. Activity partition corrected: `running` = `pending` + `in_progress`,
   `parked` = `parked` (it previously read `parked` as `pending`), `recent` =
   `completed` + `failed` capped at 20 after ordering; the endpoint takes **no**
   parameters.
7. Activity's fold-in keys on **`request_id` + highest `seq`** (was `task_id` +
   `at`) — early turn rows carry a null `task_id`.
8. `ended_at` is the `final_response` row's `at`, **null in flight** (was "the
   last row seen", which gave every interrupted turn a fake end time).
9. `stage_count` counts only the twelve NFR-020 spine names.
10. `agent` derives from `plan_created.detail.agent`, not `audit_events.actor`.
11. `conversation_id`/`task_id` resolve through the turn's task.
12. `from`/`to` are half-open on the **turn's** `started_at`, pushed into SQL as a
    `MIN(at)` group filter (a row-level window returned half a turn).
13. `getAuditTurn`'s `approval_events` are **audit rows** (lifecycle kinds ∪ rows
    whose `detail` carries `resumed_from_approval_id`), `null` when there was no
    episode — previously it returned rows from the `approvals` table.
14. `operationId` `getAuditTrace` → **`getAuditTurn`**.

## 3. Evidence

* **CAS proof ran on real PostgreSQL 17** (`postgresql+psycopg`), not SQLite. The
  Compose stack (`scripts/dev-up.sh`) correctly refuses to boot on template
  secrets, so the proof used a throwaway `postgres:17` container on port 55433
  with a locally generated password held only in the shell environment — no
  repository `.env` was written and no secret is committed. Collected ids confirm
  the parametrised leg: `test_cas_race.py::…[postgresql+psycopg]`.
* Suite green **twice** at `356 passed, 26 skipped` with the Postgres leg enabled
  and `317 passed, 26 skipped` on SQLite alone. The 26 skips are pre-existing
  Phase-2 gates (ToolManager, orchestrator, `sunil.main`), untouched here.

## 4. Boundaries observed

Not edited: `tests/contracts/**`, `tests/fakes/**`, `core/approvals/base.py`.
The QA deliverables `tests/fakes/fake_ops_store.py` and
`tests/contracts/test_c6_ops_reads.py` (C6 §6) are **not** in this branch.

## 5. Known gaps for the reviewer

* The `tasks` / `task_status_events` / `audit_events` read model in
  `ops_read_model.py` is a transcription of the spine's base schema on a private
  `MetaData`, because the spine lane has not landed `db/models.py`. **The DDL that
  adds `tasks.project_key` (C6 §3) belongs to the spine lane's base migration** —
  Stream D's own revision owns the `approvals` table alone, and adding a column to
  a table no migration creates would not run. Flag at integration.
* `ApprovalSweeper` is not yet wired into an app lifespan; `main.py`/`deps.py` are
  the platform lane's files, not this branch's. `start()`/`stop()` are the seam.
* The audit index derives `outcome`/`agent` in Python after grouping (they live
  inside JSON `detail`). The `request_id` and time-window filters are pushed into
  SQL, so the load is bounded by those; a JSON-path predicate is the optimisation
  if the audit table outgrows it.
