# S2-c4-parcel1 — C4 v1.2.0 migration, parcel 1 (the fake + the 19 frozen call sites)

**Agent:** qa_engineer (Team 21, SUNIL V2 rebuild) · **Branch:** `task/S2-c4-v120` (cut from V2)
**Contract:** `docs/contracts/C4-approvals.md` **v1.2.0** (§6.2 + the §6 clock-ownership
paragraph), migration parcel 1 of the changelog's two-parcel plan.
**Ruling:** R7 / R7.1 in `docs/tasks/integration-w1-rulings.md` (branch `task/S2-rulings`).
**File ownership (paths this parcel touches):** `apps/api/tests/fakes/fake_approvals.py`,
`apps/api/tests/contracts/test_c4_approvals.py`,
`apps/api/tests/contracts/test_c1_tool_adapter.py`, this file.
Explicitly NOT touched: `apps/api/sunil/**` (no production code), `apps/api/tests/unit/**`
(parcel 2's estate — including the two atomic-set edits below), `docs/contracts/**`.
**Status:** delivered. Suite run twice, identical counts; the only reds are parcel 2's two
named atomic-set items.

---

## 1. What changed

| # | Artefact | Change |
|---|---|---|
| 1 | `apps/api/tests/fakes/fake_approvals.py` | `decide` replaced with R7.1's body **byte-for-byte** (verified by extracting the ruling's ```python``` block and diffing it against the method as written: 1391 bytes, identical). It is now `async def decide(self, approval_id, decision, reason=None) -> Approval \| StateConflict \| None`, with `now = self.clock.now()` as the pending branch's first read of time — the service owns its clock (C4 §6 clock ownership). |
| 2 | same file, module docstring | The "deliberate design notes" bullet that declared `decide` **and** `sweep` synchronous-with-caller-`now` (citing C1 §6.4 test 5's 4-argument call) now applies to `sweep` only, and states *why* §6's clock-ownership paragraph makes `sweep(now)` the deliberate non-exception. `decide`'s bullet states the v1.2.0 shape, cites ruling R7 and the clock-ownership paragraph, and preserves the v1.0.1 return-shape clauses verbatim (`None` → 404, `StateConflict` → 409, never raises, status mapping lives in the HTTP layer). The source-of-truth pointer at the top moves `v1.1.0` → `v1.2.0` so the file does not cite a version whose §6.2 it no longer implements. |
| 3 | `apps/api/tests/contracts/test_c4_approvals.py` | 17 call sites migrated (lines 108, 134, 135, 142, 143, 149, 158, 183, 220, 241, 242, 292, 300, 311, 325, 332, 349). |
| 4 | `apps/api/tests/contracts/test_c1_tool_adapter.py` | 2 call sites migrated (lines 557, 797). |

**Call-site rule applied, mechanically and only mechanically:**
`X.decide(a, d, r, <clock>.now())` → `await X.decide(a, d, r)`. Applied by a script that
asserted exactly one regex match on each of the 19 named lines (a zero-match line aborts the
run), so no line was edited by eye and no unlisted line was touched. Every enclosing test was
already `async def` — verified before the edit, including `test_c1_tool_adapter.py:534`
(`test_c1_5_approved_id_executes_once_then_is_spent`) and `:773`
(`test_c1_allow_grant_ignores_an_approval_id_without_burning_it`).

**Semantics preserved:** every migrated site passed *the fake's own injected clock*
(`clock.now()`, `c2.now()`, `approvals.clock.now()`), which is the same object the fake now
reads internally — the caller-`now` was ceremony, not information (R7 grounds 3). The one
non-obvious case, `test_c4_approvals.py:332`, passed `c2.now()` for the second service
`approvals2`, which is constructed with `clock=c2`; identical value after migration.

**Deliberately NOT done** (parcel 2 / not this parcel): no production code; no edit to
`tests/unit/approvals/harness.py` or `tests/unit/approvals/test_mounted_surface.py`; no route
change; unused `clock` fixture parameters left in place on the tests that no longer read them
(removing them is beyond R7.1's mechanical rule, and the repo has no Python lint gate — CI's
lint jobs are yamllint/OpenAPI only).

## 2. Expected reds on this branch (the atomic set is not yet whole)

R7's ordering rule: parcel 1 + parcel 2's two test edits are ONE atomic set that must enter
the integration tree together. On this branch parcel 1 has landed and parcel 2's half has not,
so exactly two parcel-2-owned items are red. Both are the wiring engineer's, land on their
branch, and combine at integration.

| Source (owner: parcel 2) | Failing tests | Evidence |
|---|---|---|
| `apps/api/tests/unit/approvals/harness.py:63` — `FakeHarness.decide` still calls the sync 4-argument form `self.service.decide(approval_id, decision, reason, self.clock.now())`. R7.1's fix: `return await self.service.decide(approval_id, decision, reason)`. | **15** — every `[fake]` parametrisation in `tests/unit/approvals/test_real_service_contract.py` | all 15 tracebacks terminate on the same line: `harness.py:63: TypeError: FakeApprovalsService.decide() takes from 3 to 4 positional arguments but 5 were given`. The `[db]` half of the same parametrised suite is green. |
| `apps/api/tests/unit/approvals/test_mounted_surface.py:259` — `test_the_mounted_decision_names_the_gap_when_the_seam_has_no_service_decide`, the 501-asserting test. R7.1 deletes it and replaces it with the fake-wired green decision test. | **1** | fails at `:278` (`assert answered.status_code == 501`) with a **404** body, `{"error":{"kind":"not_found",...}}` — i.e. the route's `iscoroutinefunction` probe now finds the fake's awaitable `decide` and answers a contract code instead of the 501. That is R7.1's predicted behaviour and precisely why the replacement test parks INTO the fake. |

Note on the brief's pointer: the sync-style harness line is `tests/unit/approvals/harness.py:63`
(as named in R7.1), not `tests/ops_harness.py:63` — `tests/ops_harness.py` contains no `decide`
call and is untouched and green.

**No other red exists.** 16 failures total, 16 attributed, and the pass/fail arithmetic closes
against the pre-change baseline (912 → 896 passed, the 16 that moved are exactly the 16 above;
collected total unchanged at 916; skips unchanged at 4 and all pre-existing — one SQLite
StaticPool skip, three opt-in live-gateway skips).

## 3. Counts (evidence)

Command: `python -m pytest --strict-markers -q`, from `apps/api`, Python 3.13.14.

| Run | Result |
|---|---|
| Baseline, before any edit | **912 passed, 4 skipped, 0 failed** |
| After parcel 1 — run 1 | **896 passed, 16 failed, 4 skipped** |
| After parcel 1 — run 2 (determinism, as `tests.yml` does) | **896 passed, 16 failed, 4 skipped** — identical |

Frozen contract surface, green:

| Scope | Result |
|---|---|
| `tests/contracts/test_c4_approvals.py` + `tests/contracts/test_c1_tool_adapter.py` | **62 passed, 0 failed** |
| `-m contract` (every numbered frozen-contract test) | **298 passed, 618 deselected, 0 failed** |
| `tests/contracts/` (whole directory) | **298 passed, 0 failed** |

## 4. Integration note for the DM

This branch is **not mergeable alone** and must not be merged alone: merging parcel 1 without
parcel 2's two test edits imports the 16 reds above into the integration tree. Land it with the
wiring engineer's atomic-set commit (harness line + mounted-surface test replacement); the route
deletion may follow at any time after.
