# S2-close — the wave-2 closing round (backend lane)

**Branch:** `task/S2-close` (cut from V2 @`25b3c04`) · **Lane:** backend_engineer · **Date:** 2026-09-12
**Scope owned this round:** two fully-specified architect deltas (R8.1, R7.2Δ), the security
residuals from `integration-w2r1.md`, and `scripts/` (unowned this round).
**Not touched:** `tests/contracts/` and `docs/contracts/` — QA's parcel (R8.1 piece 6) follows.

---

## 1. R8.1 — the §7.5 fix (items 1–5, one atomic set)

Landed exactly per the delta, as commit 1. Each piece alone goes red or changes nothing, which is
why they are one commit:

| # | file | change |
|---|---|---|
| 1 | `core/tool_framework/base.py` | frozen `ApprovalRef(approval_id, expires_at)`; `ToolResult.approval: ApprovalRef \| None = None`, last position (the only defaulted field) |
| 2 | `core/tool_framework/manager.py` | `_error`/`_early_exit` gain a **keyword-only** `approval_ref` passthrough; BOTH park exits mint the ref verbatim from `ParkedApproval` (`_parked_in_one_transaction`'s `_parked` → `parked` — the previously discarded value); `_normalise`'s `replace(...)` gains `approval=None` (step-7 forge close) |
| 3 | `agents/project_manager/agent.py` | reads the typed field; stops mining `data` |
| 4 | `tests/integration/tool_manager_double.py` | the lying `ToolResult(data={...})` wrapper and its doubly-false comment deleted, replaced with the real shape |
| 5 | `tests/integration/test_double_conformance.py` | NEW, the ruling's verbatim code |

`agent.py:88-89` and `turn.py:430-431` needed no edit, as the ruling predicted: the dict keys keep
their names and are now truthfully populated. `turn.py`'s `or ""` is left in place as type
narrowing — unreachable-by-contract.

### Proving it live-shaped, not shape-only

The defect was invisible to the suite because the double lied, so the red had to be demonstrated on
the REAL manager. Before any production edit, the integration `conftest.py` was pointed at
`ToolManager`:

```
{"stage": "final_response", "summary": "turn parked awaiting owner approval",
 "detail": {"outcome": "parked", "approval": "none"}}
2 failed, 11 passed
```

That is §7.5's live evidence line, reproduced. After the atomic set, same test, same tracing point:

```
{"stage": "final_response", "summary": "turn parked awaiting owner approval",
 "detail": {"outcome": "parked", "approval": "apr-1"}}
```

and the C5 envelope itself:

```json
{"outcome": "parked", "approval": {"approval_id": "apr-1",
 "expires_at": "2026-01-04T00:00:00Z", "summary": "fake_tool.write_item requires approval"}}
```

The conformance test's own red was the double's lie, caught verbatim:
`assert {'approval_id': 'apr-1', 'expires_at': '...'} == None`.

### Tests added in this lane

* `tests/integration/test_governed_turn.py` — the parked-turn test now asserts `approval_id != ""`
  **and** that it resolves in the C4 store (`in approvals.parked`, `expires_at` equal to the parked
  row's). Truthiness alone would not have caught the wave-2 defect, because the double filled the
  field in from a channel the real manager never populates.
* `tests/unit/core/tool_framework/test_manager_pipeline.py` — two probes at the manager level:
  the park exit mints the ref verbatim (`data is None` asserted alongside), and the **forged-approval
  clearing** twin of contract test 10 (an adapter handler returning
  `approval=ApprovalRef("apr-forged", ...)` gets `approval is None` back, and nothing is parked).
  Contract test 10's body is QA's parcel; this is the unit-level twin.

---

## 2. R7.2Δ — reconciliation rule 4 + lazy-expiry finalisation

Landed exactly per the delta, all four pieces, in `core/approvals/service.py`:

1. `ReconciliationReport` gains the `finalised` bucket (`__slots__`, `__init__`, `total`,
   `__repr__`; docstring "three rules" → "four rules").
2. `AUDIT_TASK_RECONCILED = "task_finalisation_reconciled"` — deliberately **not**
   `AUDIT_RECONCILED`, which C4 §3 rule 3 names for the consumed case.
3. Rule 4 in `reconcile_on_startup`: a third select in the existing `engine.connect()` block, a
   fourth loop after rule 3's, `is_finalised`-guarded. Scan posture recorded in the code comment.
4. `decide`'s lazy expiry: `.returning()` so the audit row is conditioned on the CAS actually
   transitioning (a raced-away UPDATE previously wrote a phantom `decide_past_ttl` row), the
   conflict return moved out of the transaction, and finalisation through the same door `sweep()`
   uses — after commit, `is_finalised`-guarded, failure logged-not-raised so the 409 stands.

The four pinned tests are transcribed verbatim into `tests/unit/approvals/test_reconciliation.py`,
with the `RecordingTasks.fail_next` failure valve. Red first: `ImportError: cannot import name
'AUDIT_TASK_RECONCILED'`. The existing suite stayed green exactly as the ruling predicted — rule 2's
freshly expired rows reach rule 4 with their tasks already finalised, so the guard skips them and
`test_reconciliation_is_idempotent`'s totals hold.

---

## 3. Security residuals (from `integration-w2r1.md`)

**R-1a (Security's priority) — CLOSED.** The factory's guard was
`hasattr(approvals, "engine") and callable(getattr(audit_hook, "attempt_on", None))`. The two
conditions mean different things and have different correct answers: an in-memory C4 fake has no
transaction to share (build without the collaborator — correct), whereas a database-backed C4
service beside a hook that cannot write on a caller's connection is a broken deployment. The `and`
made the second boot **quietly** on the non-transactional path, reopening the window Security
condition C-1 closed. Now the guard is the engine alone and `TransactionalApprovals`' constructor
raises, which is what it was written to do. Test:
`test_a_database_c4_seam_with_a_non_conforming_audit_hook_refuses_to_boot` — red first, "DID NOT
RAISE TypeError".

**R-1b — CLOSED.** The `hasattr` is hoisted out of the per-plan closure to a boot literal
(`transactional_c4`). The resolved C4 seam cannot change shape between plan executions.

**R-6a — CLOSED, proved by insertion.** The ADR-033 lane tripwire's layer 3 matched `node.module`
only, so `from sunil import settings` in a routing module read as module `sunil` — forbidden of
nobody — while binding the lane-carrying module itself. Inserting that exact line into `router.py`
left **all 17 tripwire tests green**. The fix also matches `module + "." + alias.name`; with the
dodge still inserted it goes red (`router.py:34 imports sunil.settings`) and green again on revert.
`router.py` is byte-identical to HEAD.

**D-1 — CLOSED (doc moves, behaviour stays).** `S2-wiring.md` §1 said a failed lifespan `start()` is
"the same class of event" as a build failure and "gets the same treatment". It is not: a build
failure precedes the registry (the tool is genuinely absent, `unknown_operation`), while a lifespan
`start()` failure follows it — the adapter is already in `registry.adapters` and in the catalogue
the planner reads, so the tool is **present with a dead transport** and fails as `transport_error`.
`main.py`'s own warning already said so; the doc and the one inline comment that contradicted it now
agree with the code.

Not in this round (still open in the register): R-1c `_pending_events` growth on caller-rollback,
R-3a `base_url_env` grantable-URL allowlist symmetry, QA F2's tripwire count claim.

---

## 4. Scripts (`scripts/dev-up.{sh,ps1}`)

Both twins, identical behaviour:

* **DATABASE_URL password sync.** Generating `POSTGRES_PASSWORD` without rewriting the password
  embedded in `DATABASE_URL` produced a fresh `.env` that boots the stack and then refuses every
  application connection — and the old code only *warned*, so the failure surfaced later as an auth
  error with no link to a message that had scrolled past. The userinfo password is now rewritten in
  place and the rewrite is **verified**; if the template ever stops matching the expected shape the
  script refuses loudly (removes the half-made `.env`, prints the by-hand instructions, exits 1)
  rather than warn-and-boot. Verified against the real `.env.example` on both twins: password
  swapped, host/port/database preserved, no other line touched, and the unmatched-shape path
  returns false.
* **`localhost` → `127.0.0.1`** in the wait loop's success summary. ADR-032 binds every published
  port to `host_ip 127.0.0.1` (the CI port gate asserts it), so nothing listens on `::1` while
  `localhost` resolves to `::1` first on a dual-stack host — psql/curl/the browser wait out a v6
  connection timeout before falling back, which reads as "the stack is up but hangs".

CI guards re-run locally: ASCII-only and LF-only across all four scripts plus the postgres init
script; `shellcheck --severity=warning` clean; `dev-up.ps1` parses clean under **Windows PowerShell
5.1** (not only pwsh 7, which is the gap `CI.md` records).

---

## 5. Double retirement (R8's same-wave follow-up)

Its own charter: *"When Stream A lands, this file is deleted and the integration test constructs
`ToolManager(adapters, permission_hook, approvals, audit_hook)` instead — the same constructor
shape, which is why the swap is a one-line change."*

Condition met: the integration suite is **green on the real manager, 14/14, with no divergence**.
`conftest.py` takes the real chokepoint; `tool_manager_double.py` and `test_double_conformance.py`
are both deleted (the conformance test polices a double, so it dies with it). Nothing to record
under the "keep both and say why" branch.

No `transaction=` is passed in the integration fixture: the C4 seam there is
`FakeApprovalsService`, which has no engine to share — the same decision `api/wiring.py` makes at
boot, and after R-1a it is made on the same single condition.

---

## 6. Suite

Green twice on both legs, throwaway Postgres container (`postgres:17-alpine`, `127.0.0.1:5445`,
disposed after):

| leg | baseline | this branch |
|---|---|---|
| SQLite | 947 passed, 4 skipped | **954 passed, 4 skipped** (×2) |
| Postgres | 992 passed, 4 skipped | **1003 passed, 4 skipped** (×2) |

Accounted: +2 manager-pipeline probes (SQLite-only, unparametrised) +1 wiring factory test, plus
the 4 reconciliation tests, which are engine-parametrised — 4 on the SQLite leg, 8 on the Postgres
leg. The conformance test was added and then retired with the double, net 0.

## 7. Commits

```
66f678d R8.1: the park exit's approval reference becomes a typed C1 field
f5dd129 R8 follow-up: retire the integration ToolManager double
ab0c21f R7.2Delta: reconciliation rule 4 + the decide-time lazy-expiry finalisation
84f538a security residuals R-1a, R-1b, R-6a, D-1
58fee1e scripts: sync DATABASE_URL's password, and stop advertising localhost
```

**Boundaries observed:** `apps/api/tests/contracts/` and `docs/contracts/` untouched (verified by
`git diff --name-only` over the whole branch). No frozen suite, no contract file, no route moves.
Not merged — review owed.
