# S-C6-fakes — `FakeOpsStore` + the C6 contract suite

**Agent:** qa_engineer (Team 21, SUNIL V2 rebuild) · **Branch:** `task/S-C6-fakes`
**Contract:** `docs/contracts/C6-ops-reads.md` v1.0.0 (FROZEN 2026-09-11) §6, and
`docs/contracts/C6-ops-reads-openapi.yaml` v1.0.0.
**Status:** delivered — suite green twice, deterministic. Resumed from the owner-paused
wip commit `6ffcd5f`.

---

## 1. What was delivered

| Artefact | Path | Note |
|---|---|---|
| The fake | `apps/api/tests/fakes/fake_ops_store.py` | `FakeOpsStore` + `ops_fixture()`, C6 §6 |
| The seam | `apps/api/tests/fakes/ops_seam.py` | `OpsReadStore` Protocol, C6 §5 transcribed |
| The suite | `apps/api/tests/contracts/test_c6_ops_reads.py` | the ten §6 tests (wip, completed) |
| Conformance | `apps/api/tests/contracts/test_fake_conformance.py` | `FakeOpsStore → OpsReadStore` row |
| OpenAPI | `apps/api/tests/contracts/test_openapi_contracts.py` | C6 is now the third walked document |

Nothing outside `tests/fakes`, `tests/contracts` and this file was touched. **No production
code was written** — QA does not implement the thing it verifies.

## 2. Evidence

```
baseline (C6 file excluded)   146 passed,  25 skipped
after this task, run 1        268 passed,  30 skipped   in 0.76s
after this task, run 2        268 passed,  30 skipped   in 0.76s   (identical — determinism)
  of which test_c6_ops_reads  106 passed,   5 skipped
```

Delta **+122 passed / +5 skipped**: 106 C6 contract tests, 3 conformance tests (the new
fake × the three parametrised guards), 3 structural OpenAPI tests (C6 added to the
parse/`$ref`/orphan walks) and 10 new C6-specific YAML assertions.

The five skips are the C6 route-level clauses, behind the F5 import guard with a loud
reason (`missing: sunil.main`). They are **not** forever-skips: they activate the moment
`sunil/api/routes/{tasks,activity,audit}.py` and `api/deps.py` land.

### Mutation proof (the tie-order law)

`fake_ops_store.py::list_tasks` — the sort key, mutated to compare the id **numerically**
instead of as a plain string (the exact F8 misreading C6 §2.1(1) forbids):

```python
# before (correct)
rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=newest)
# mutant
rows.sort(key=lambda row: (row["created_at"], int(row["id"].split("-")[1])), reverse=newest)
```

Result: **5 failed, 101 passed** — `test_c6_1_default_order_is_created_at_desc_then_id_desc`,
`test_c6_1_equal_created_at_pair_orders_lexicographically`,
`test_c6_1_order_oldest_reverses_both_keys`,
`test_c6_2_exactly_full_final_page_returns_a_cursor_then_an_empty_page`,
`test_c6_2_short_page_ends_the_walk_with_a_null_cursor`, failing on
`At index 23 diff: 'task-10' != 'task-9'`. Reverted → 268 passed, 30 skipped.

## 3. Two defects found in the paused wip, and fixed

The wip commit `6ffcd5f` contained the test file only — no fake — so the **whole suite
failed to collect** (`ModuleNotFoundError: tests.fakes.fake_ops_store`), not just C6. Once
the fake existed, two wip assertions turned out to be self-contradictory:

1. **`test_c6_5_the_projection_passes_all_three_contracted_keys` probed a row its own cap
   removes.** It looked for `task-12` in `activity().recent`, but C6 §2.3 caps `recent` at
   20 and the fixture seeds 21 *newer* terminal tasks — `task-12` is the 27th of 27, and
   `test_c6_5_recent_is_capped_at_the_twenty_newest_terminal_tasks` in the same file proves
   it is excluded. Fixed by moving the probe to the **parked** row (`task-5`), whose latest
   audit row is the continuation's `tool_result`; that row now carries all three contracted
   keys beside the lineage key and an untrusted excerpt, so the allow-list has something to
   pass and something to drop.
2. **`test_c6_10_no_surface_escapes_encodes_or_strips_anything` could never pass.** It
   asserted `UNTRUSTED_SUMMARY in json.dumps(...)` while
   `test_c6_10_the_untrusted_fixtures_actually_carry_dangerous_bytes` requires that same
   string to contain an ASCII `"` — which `json.dumps` always escapes. Fixed by comparing
   the **JSON-encoded form** (`json.dumps(raw, ensure_ascii=False)[1:-1]`). Quote-escaping
   is JSON *syntax*, undone by every parser; the transforms the test exists to catch (HTML
   entities, `\uXXXX` escaping of printable characters, tag stripping) are not syntax and
   still fail the comparison and the forbidden-substring sweep that follows it.

## 4. Decisions where C6 §6 left room, recorded

1. **Clock convention: stamp-then-advance.** §6 says each helper "advances the clock +1 s
   unless an explicit timestamp is passed" without fixing the order. A row takes the
   current value and *then* advances, so the first seeded row is `00:00:00`. This is what
   makes the fixture's timeline land where the suite's literal timestamps say it does
   (33 task rows consume `:00`…`:31`, audit rows run from `:32`).
2. **The tie needs exactly one auto row.** `task-9` is seeded with an explicit `TIE_AT`
   and `task-10` takes the same second from the clock. Both explicit would need `TIE_AT`
   to fall strictly between two consecutive whole seconds, which does not exist; both auto
   could never tie. `ops_fixture()` **asserts** `task-10`'s `created_at == TIE_AT` and
   fails with a written reason if the seeding cadence ever shifts, so this never degrades
   into a baffling order-law failure.
3. **Five audit turns, not three (a superset).** §6's fixture paragraph names `req-full`,
   `req-parked` and `req-live`. Its contract test 7 additionally demands the `outcome` and
   `agent` filters of §2.4 and a cursor walk on the audit index, which three turns — two of
   them with a null outcome — cannot exercise. Added `req-failed` (the failed-outcome and
   `failure_kind`/`agent` derivations) and `req-proj` (the projection leak probe, and a
   second row inside the `from`/`to` half-open window). Additive only: no §6 clause is
   contradicted. **Flagged to the Solution Architect** in case the literal "three" was
   meant as a maximum.
4. **`req-parked` omits `permission_decision`.** Its nine pre-park spine rows must include
   `tool_result` (contract test 8 requires a spine name to appear on both sides of the
   partition). The narrative: the first tool needed no decision, and the second tool's
   decision *is* the approval episode (ARCHITECTURE_V2 §6 Leg 3).
5. **`OpsReadStore` lives in `tests/fakes/ops_seam.py`.** The production module C6 §5 implies
   (`sunil/core/ops/base.py`) is Phase 2 work and QA writes no production code. The
   Protocol is transcribed there so the F2 `_check` witness has a yardstick; that module's
   docstring carries the **one-line swap** to re-export the real Protocol when Stream D
   lands it, at which point the conformance test starts checking the fake against the real
   seam and fails if the signatures drifted.

## 5. Open / handed back

* **Contract test 9, clauses 1–3 are stubs that fail loudly, not full bodies.** The
  no-session-401, missing-client-header-403 and bearer-401 clauses need a session-minting
  helper, the app's Origin handling and a test client; `fastapi` is not even a dependency
  of `apps/api` yet, so any body written now would be unverifiable and would hard-code an
  API the implementer has not chosen. They are import-guarded and call `pytest.fail` with
  the exact assertion list they must grow once the modules exist. The **structural** half
  of the ADR-035 probe (a route-table walk matching `require_service_token` by function
  identity) and the read-only route-table assertion are full bodies today. *Action:
  whoever builds the ops routes runs this file first — it will be red with instructions.*
* **Q2's `tasks.project_key` is assumed present** as C6 §3 rules. The fake carries it; the
  migration is Stream D's.
* The fake is the store Stream D builds against; it is **not** a substitute for a
  database-backed conformance run. Ordering, cursor and half-open-window behaviour must be
  re-proved against the real SQL implementation — plain-string `ORDER BY … id DESC` and
  half-open `started_at` comparison are exactly where a real query diverges from a Python
  sort.
