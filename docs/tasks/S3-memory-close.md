# S3-memory-close — R13 wiring, the `memories` reaper, and the two QA coverage holes

Lane 3 of w2r3. Branch `task/S3-memory-close`, cut from `V2`. Applier: backend
engineer. Sources: `docs/tasks/integration-w1-rulings.md` (R12 rule 3, R13, R15)
and `docs/tasks/w2r3-conditions.md` (QA F-2, DC-23 pre-work).

---

## 1. R13 — `EntityResolver` wired into `MemoryService`

Stream C built the resolver and left it unwired, so `MemoryScope(kind="project",
id="pda")` reached the provider with the human key still in it: every memory
about a project was filed under the literal string `"pda"`, in a scope nothing
that resolves ids would ever read. The delta, applied exactly as ruled:

| R13 item | Where |
|---|---|
| 1 — keyword-only `resolver: EntityResolver \| None = None` | `core/memory/service.py::MemoryService.__init__` |
| 2 — resolve INSIDE `asyncio.timeout(self._budget_s)` | `MemoryService.recall` |
| 3 — resolve BEFORE the audit row is minted; both errors surface | `MemoryService.write` |
| 4 — the construction site passes `resolver=EntityResolver(engine)` on the engine branch | `api/wiring.py::build_memory_service`, called from `main.py` |
| 5 — R12 rule 3 in the SERVICE, not the resolver | `MemoryService._resolve_for_write` / `_materialise_from_registry` |
| 6 — the owed tests | `tests/unit/memory/test_service_resolution.py` (+ 4 in `test_wiring.py`) |

Two notes a reviewer should check on purpose.

**The construction site was `main.py`, not `wiring.py`.** R13 item 4 names
`wiring.py`, and `wiring.py` is where the decision now lives
(`build_memory_service`), but `main.py` was constructing `MemoryService(
memory_provider)` by hand — so a resolver added to `wiring.py` alone would have
been wired into nothing. `main.py` therefore changes by three lines (build the
service, hand it to the turn executor, drop a now-unused import) and
`test_the_composed_app_gives_its_turn_executor_a_resolved_memory_service` pins
the call site rather than the builder. **Lane note for the DM:** `main.py` is
outside lane 3's stated file list; the edit is minimal and localised.

**`EntityResolver` gained a read-only `engine` property**, so the service can run
R12 rule 3's `upsert_entity` on the SAME engine without opening a second one onto
the entity tables. The resolver's job stays "key → row id"; materialisation is
the service's decision, per R13 item 5.

`MemoryService` also gained a read-only `provider` property — the composition
root needs the store for the reaper's `delete_expired`, and reaching into
`_provider` from `main.py` would have been a private attribute in the
composition root.

### R12 rule 3, as implemented
Registry → table, lazily, on **write** only. The registry is consulted ONLY after
the entity table has already said "unknown", so an existing entity is never
re-created; `upsert_entity` is idempotent on `key`. A key in neither place stays
`MemoryScopeError`, and **recall never materialises** — a read must not mutate.

---

## 2. The `memories` reaper (R15, S2-C §7.4)

* `core/memory/reaper.py::MemoryReaper` — the runner (`run_once`/`start`/`stop`,
  injected `sleep`), cadence `DEFAULT_INTERVAL_S = 3600`.
* `memory_providers/pgvector_provider.py::delete_expired()` — the SQL. The
  predicate is the recall filter INVERTED, so the reaper can only ever remove
  rows recall was already hiding; `expires_at IS NULL` is untouched; links
  cascade. **Not on C3's `MemoryProvider` Protocol** — C3 binds recall
  visibility, not storage hygiene, so no contract moves (R15's own words).
* Kill switch `SUNIL_MEMORY_REAPER_ENABLED`, **default ON**, with a row in
  `.env.example`. Tested both ways.
* Audit: one row per reap batch, **count only** (`record_memory_reap(deleted=n)`)
  — a reaper that recorded which memories it destroyed would copy expired,
  often most-private, content into the one store retention cannot clear. A batch
  that deleted nothing, or a batch that failed, writes no row.

### The asymmetry, argued (the condition asked for the argument)
`ApprovalSweeper` is contained on the tick and **propagating on startup**. This
reaper is contained on the tick and has **no startup leg at all**, and that is a
decision rather than an omission:

* the sweeper's startup half is a ONE-SHOT SAFETY PROPERTY — a
  consumed-but-unfinalised continuation must be failed before anything else runs
  (C4 §3 / ADR-031); an API that booted having skipped it leaves interrupted
  continuations looking runnable;
* deletion has no equivalent. It is **idempotent** (a second pass matches
  nothing), it is **lazy-guarded** (C3's TTL filter already hides exactly what
  this deletes, so nothing is exposed by a late reap), and it is time-driven
  rather than boot-driven. A reap missed at boot costs nothing the next tick does
  not fix, so refusing to boot on it would buy a new outage mode for no safety.
* The tick stays contained for the sweeper's reason, sharpened: nothing else
  deletes these rows, so a reaper that died on one transient blip leaks rows
  forever.

**Audit sink seam, and what is still owed.** The batch row goes through an
injected `ReapAuditSink`, exactly like the approvals service's `AuditSink` and
`MemoryService`'s own audit sink — and, exactly like the approvals one, **no
production implementation exists yet**. It cannot be an `audit_events` row: that
table's `stage` is ADR-023's frozen set of twelve TURN stages ("the SET of twelve
does not grow"), and a reap is not a turn. Writing one under a borrowed stage
name would be a false statement in the trail. **Owed, named here for the DM:** a
system-event audit sink (non-turn records) is the instrument this row belongs in;
until it exists the reaper logs the failure type only and the seam is filled by
tests. THREAT_MODEL DC-22's "no reaper" clause is now half-closed — deletion
exists; the retention RECORD does not.

---

## 3. QA F-2 — the production park exit's `ApprovalRef`

`tests/unit/core/tool_framework/test_chokepoint_transaction.py` (the REAL
`ToolManager` + `DatabaseApprovalsService` + `DbToolAuditHook`, engine-parametrised)
gains two tests: the transactional park exit's reference is asserted against the
COMMITTED approval row (id and rendered expiry), and the IFF's other half — a
non-`approval_required` result carries no reference.

**Mutation evidence (the verification the condition asked for), re-run against
the finished tree on 2026-09-18.** With `approval_ref=None` substituted at
`manager.py:527` — the whole `ApprovalRef(...)` expression replaced, not a field:

```
FAILED tests/unit/core/tool_framework/test_chokepoint_transaction.py::
       test_the_production_park_exit_surfaces_the_typed_approval_reference[sqlite+aiosqlite]
1 failed, 1110 passed, 57 skipped
```

One test in the whole tree fails — which is F-2's finding restated as a fact: the
mutant survives every other test in the suite. (The QA finding was written
against `V2`, where it survived *all* of them.)

The IFF's other half was mutated too, because a test that only ever asserts
"non-None" can be satisfied by a reference minted everywhere. Substituting
`approval=approval_ref or ApprovalRef(approval_id="drifted", …)` in `_error` —
the "just always attach it" convenience drift the second test exists to stop:

```
FAILED tests/contracts/test_c1_tool_adapter.py::test_c1_5_approved_id_executes_once_then_is_spent
FAILED tests/unit/core/tool_framework/test_chokepoint_transaction.py::
       test_only_the_park_exit_mints_a_reference[sqlite+aiosqlite]
2 failed, 1109 passed, 57 skipped
```

Both mutants were reverted and `manager.py` is byte-identical to `V2`
(`git diff bd30610 -- …/manager.py` empty); **no production line in that module
was touched by this branch** — F-2 was a coverage hole, and coverage is all that
was added.

---

## 4. DC-23 — ground left honest, gate NOT closed

`agents/project_manager/agent.py`'s recall-framing site carries a loud comment
naming THREAT_MODEL DC-23 and its three open controls (system-role framing, no
byte cap, no `local_only` filter), the survivable-today reason (nothing writes
memories yet) and the owner (the memory-write wave). **Comment only, no
behaviour change** — the gate stays with the write-path wave.

---

## 5. Proof

| Gate | Result |
|---|---|
| Suite, SQLite leg, run 1 / run 2 | **1114 passed, 57 skipped** (both) — baseline `V2` was 1085 / 47 |
| Suite, Postgres leg | **still not run on this machine** — see §6.1, which is now an escalation, not a note |
| Tests added | **39** (29 that run on the SQLite leg + 10 Postgres-gated) |
| Mutation, `approval_ref=None` at manager.py:527 | 1 failed / 1110 passed — the new test, alone |
| Mutation, `await reaper.start()` removed from the lifespan | 1 failed / 798 passed (`tests/unit`) — the lifespan test, alone |
| Mutants run this session, one at a time, each reverted | **10**, all caught — §5.1 / §5.2 / §3 |
| DC-23 comment | 11 added lines in `agent.py`, **0 of them non-comment** (`git diff … \| grep '^+' \| grep -v '^+ *#'` → empty) |

### 5.1 Ground-truth re-verification (2026-09-18, third session on this lane)

The two sessions before this one ended at a boundary mid-build, so **nothing above
was taken on trust**: the environment was rebuilt (`uv venv` + `-e .[dev]` in
`apps/api`, no extra packages — the package set is byte-identical to the
reference worktree's), the suite was re-run, and every ruled property was
re-proved by mutation rather than by reading the test.

Suite as inherited, SQLite leg: **1111 passed, 57 skipped** — the interrupted
session's figure, independently reproduced before a line was touched. With
§5.2's three additions it is **1114 passed, 57 skipped**, run twice, identical
both times.

What was KEPT from the interrupted session, and why: all of it. Every test in
the wip commit asserts a property one of this session's ten mutants confirms is
load-bearing, so there was nothing to rewrite — the two things the session was
missing were the verification itself and §5.2's gap.

**R13 mutation ledger.** Each mutant was applied alone, the subset run, then
`git checkout --` reverted it (tree verified clean after each):

| Mutant (production code) | Ruled property it breaks | Result |
|---|---|---|
| `resolve` moved OUTSIDE `asyncio.timeout(self._budget_s)` in `recall` | R13 item 2 — one budget covers resolve + vendor | **1 failed** — `test_resolution_and_the_vendor_call_share_one_recall_budget`, alone (47 passed) |
| audit row minted BEFORE `_resolve_for_write`, sink given the unresolved scope | R13 item 3 — resolve precedes the row; a failed resolve writes none | **2 failed** — `…raises_through_write_before_the_audit_row`, `…outage_surfaces_on_write_with_no_audit_row` (46 passed) |
| `resolver = None` on `wiring.build_memory_service`'s engine branch | R13 item 4 — the engine branch wires a resolver | **2 failed** — `test_the_engine_branch_builds_a_service_with_a_resolver`, `test_the_composed_app_gives_its_turn_executor_a_resolved_memory_service` (14 passed) |

The third mutant is the one that matters for the lane's whole reason for
existing: it is the exact state `V2` shipped in (a built resolver, wired into
nothing), and before this branch **no test in the tree failed on it**.

**Reaper mutation ledger** (same protocol — one mutant at a time, reverted,
tree verified clean):

| Mutant (production code) | Property it breaks | Result |
|---|---|---|
| `sunil_memory_reaper_enabled` default flipped to `False` | kill switch defaults **ON** (§2) | **2 failed** — `test_the_reaper_is_built_by_default`, `…started_on_boot_and_cancelled_on_shutdown` |
| `await reaper.start()` deleted from the lifespan | a built reaper that never runs deletes nothing | **1 failed**, alone, out of the whole `tests/unit` tree (798 passed) |
| the `try/except` removed from `run_once` (the tick propagates) | containment — a transient blip must not kill the loop | **4 failed** — the two error-posture tests, the keeps-ticking test and `test_start_has_no_propagating_leg_at_all` |
| `if deleted and …` → `if …` (an empty batch writes a row) | the trail records the EVENT, not the schedule | **1 failed** — `test_a_batch_that_deleted_nothing_writes_no_audit_row` |

The count-only shape is pinned positively too, not just by omission:
`RecordingAudit` captures the entire keyword payload and the assertion is
`audit.rows == [{"deleted": 7}]`, so a future field carrying memory content
fails the test rather than slipping past an `assert deleted == 7`.

### 5.2 `tests/unit/memory/test_reaper_predicate.py` — the one gap this session closed

Mutating the reaper's SQL exposed the hole the skipped Postgres leg leaves. The
destructive half of this lane — *which* rows the delete matches — was graded
**only** by `test_reaper_sql.py`, and on a machine with no Docker daemon that
file skips. Dropping `expires_at IS NOT NULL` from the predicate therefore left
the whole SQLite leg green while the statement destroyed every
"keep until superseded" memory in the store: the rows with no TTL, which is to
say the ones the owner never asked to expire.

So the same production statement is now graded with no server. The provider is
real, the statement is the one `delete_expired` builds (never restated in the
test — a test that rebuilt the `delete()` would pass against itself), and only
the transport is a double: an engine that records what was executed inside
`engine.begin()` and reports a row count. SQLAlchemy compiles it against the
REAL Postgres dialect and the assertions are on the emitted SQL.

| Mutant | Result (whole `tests/unit/memory`) |
|---|---|
| `expires_at IS NOT NULL` dropped | **1 failed** — `test_the_reaper_deletes_only_what_the_recall_filter_already_hides` |
| boundary inverted, `<=` → `>` (delete the LIVE rows) | **1 failed** — same test |
| `int(result.rowcount or 0)` → `result.rowcount` | **1 failed** — `test_a_driver_that_reports_no_rowcount_counts_as_zero` |

Each of those three mutants was caught by this file **alone**, with the ten
Postgres-gated tests skipping beside it. This does not replace the Postgres leg
(rows really moving, `ON DELETE CASCADE` really cascading, still §6.1's owed
work) — it means a machine that cannot run Postgres can no longer ship a reaper
that deletes the wrong rows.

## 6. Open / owed

### 6.1 The Postgres leg — ESCALATION, third session running

**Still not run, and the blocker is the machine, not the branch.** This suite has
no SQLite fallback by design (a vector search SQLite cannot run would pass
against nothing), so the 10 Postgres-gated tests — `test_service_resolution.py`'s
6 and `test_reaper_sql.py`'s 4 — SKIPPED LOUDLY rather than ran, for the third
lane session in a row.

What was tried on 2026-09-18, in order, before giving up (~15 min):

* `docker version` → client 29.8.0 fine, **`Error response from daemon: Docker
  Desktop is unable to start`**;
* Docker Desktop was already running (9 processes) and the `docker-desktop` WSL2
  distro reported `Running` — so it was started, waited on for 200 s, and polled;
* the `\\.\pipe\dockerDesktopLinuxEngine` named pipe **appeared**, and every
  subsequent `docker ps` / `docker version` then **hung** rather than erroring —
  a wedged engine, not a missing one;
* full restart: Docker processes killed, `wsl --shutdown` (completed cleanly),
  Docker Desktop relaunched, polled every 10 s for 240 s — never came up;
* `wsl -d docker-desktop -- docker …` is refused by Docker Desktop itself
  ("not supported"), so the in-distro daemon is not a way round it;
* no native Postgres on this host either — nothing listening on 5432–5436, no
  `psql` on `PATH`, no PostgreSQL install directory;
* final state, re-checked ten minutes after the restart: the pipe is **gone
  again** and `docker ps` now fails fast instead of hanging. Engine mode ruled
  out as the cause — `settings-store.json` still reads `WslEngineEnabled: true`
  and `docker context show` is `desktop-linux`. (One remediation attempt invoked
  `DockerCli.exe -SwitchDaemon`, which switches to the *Windows* engine rather
  than restarting; it timed out with `context deadline exceeded` against the
  already-unresponsive backend and changed nothing — those two readings are the
  proof. Recorded so a reviewer who finds `-SwitchDaemon` in this lane's shell
  history knows it was a misfire that left no state behind.)

**What the DM needs to decide**, because a fourth attempt on this machine will
produce the same paragraph: run the leg where a daemon works (CI, or another
device), with the blessed throwaway pattern from integration-w2r2 §5 —

```
docker run --rm -d -p 5435:5432 -e POSTGRES_PASSWORD=… --name sunil-pg \
  pgvector/pgvector:0.8.6-pg17
SUNIL_TEST_DATABASE_URL='postgresql+psycopg://postgres:…@127.0.0.1:5435/postgres' \
  .venv/Scripts/python -m pytest -q          # expect 1124 passed, 47 skipped
```

Mitigation landed rather than waited for: §5.2's predicate file, which moves the
*destructive* property — which rows the delete matches — onto the leg that runs
everywhere. What the Postgres leg still uniquely proves: rows really disappearing,
`memory_entity_links` really cascading, `EntityResolver` really resolving a `key`
to a row id against the real entity schema, and R12 rule 3's upsert really being
idempotent. **None of that has been executed yet on any machine.**
2. The reaper's audit sink has no production implementation (see §2).
3. DC-23 remains open, by design (see §4).
