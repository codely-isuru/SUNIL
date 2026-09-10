# Task — P0-fakes: C1–C4 fakes and contract test suites

Owner (typeKey): qa_engineer · Status: in-review
**File ownership** (paths only this task may touch):
`apps/api/**` (new tree), `.github/workflows/tests.yml` (new file),
`docs/tasks/P0-fakes.md` (this file).
Explicitly NOT touched: `docs/contracts/**`, `docs/decisions/**`, `infra/**`,
`.github/workflows/ci.yml`.

## Static spec (from the Stage-4 issue)

**Background.** Phase 0 exit criteria 3 and 4 of the SUNIL V2 rebuild: the frozen
contracts C1–C5 (v1.0.0, 2026-09-10, post-fix-round) need executable fakes and
contract suites so that the six Phase 2 streams can build against a seam that is
proven, not described. ARCHITECTURE_V2 §3: "nothing merges without its contract
tests passing against the fakes".

**Objective.** Transcribe the frozen C1–C4 interfaces into `apps/api/sunil/`,
build every fake named in each contract's fake specification, and implement each
contract's numbered test list — red first, then green against the fakes.

**Acceptance criteria.**
1. Scaffold per ARCHITECTURE_V2 §2's module layout; package `sunil`; runtime
   dependencies limited to what the contracts force; `.venv` never committed.
2. Interfaces transcribed exactly — names, signatures, types, error classes,
   enums. Zero business logic. Docstrings cite the contract section.
3. Fakes byte-exact where the spec names exact behaviour.
4. Every numbered contract test implemented, or an explicitly-skipped stub
   citing its number and the missing production module. Never a faked pass.
5. New CI workflow running the suite on Python 3.13; `ci.yml` untouched.

**Test requirements.** Full suite green locally, run twice (deterministic, no
network); mutation proof that a broken frozen property is caught; yamllint clean
on anything touched.

**Security considerations.** Three frozen security properties are asserted
structurally, so an implementer cannot erode them silently:
`CompletionRequest` has no `tools` field (C2 §2 — the only path to a tool call is
a validated plan step through the C1 chokepoint); the approvals webhook payload
cannot carry `params_redacted` (C4 §2, redaction by shape); the bearer scheme is
declarable only against the chat contract (ADR-035 / C5 §2.3).

**Rollback.** The whole task is additive on `task/P0-fakes`; reverting the branch
removes `apps/api/` and the new workflow, leaving `ci.yml`'s test job back on its
"no application code yet" placeholder path.

## Cross-lane consumers

- `apps/api/tests/fakes/*` → consumed by Streams A/B/C/D/E/F in Phase 2 (each
  stream tests against these fakes; ARCHITECTURE_V2 §3's table names which).
- `apps/api/sunil/{core/tool_framework,core/memory,core/approvals,providers}/*`
  → consumed by the engineers implementing C1–C4; **the transcription is
  reviewed by a backend engineer before merge** (independent check that the
  frozen interfaces were copied, not reinterpreted).
- `apps/api/pyproject.toml` → consumed by `ci.yml`'s existing `test` job, which
  auto-activates now that this file exists (it probes for
  `apps/api/pyproject.toml`). No change to `ci.yml` was needed or made.
- `tests/fakes/canonical.py::args_hash` → the Tool Manager implementer must
  produce an identical digest; C1 contract test 4 compares against this
  independent implementation.

## Progress

- [2026-09-10 | qa_engineer] Branch `task/P0-fakes` verified at the merged `V2`
  tip with no prior commits (a previous dispatch left none). Read C1–C5 + both
  OpenAPI YAMLs, ARCHITECTURE_V2 §2, and the fix-round changelogs in full before
  writing anything.
- [2026-09-10 | qa_engineer] Scaffold + C4 (commit `e01ad5b`): red on
  `ModuleNotFoundError`, then `sunil/core/approvals/base.py` +
  `FakeApprovalsService` → 15 passed. C4 is the only contract whose numbered
  tests are entirely satisfiable by its own fake, so it went first.
- [2026-09-10 | qa_engineer] C1 (commit `dcf252d`): red, then
  `sunil/core/tool_framework/base.py` + `FakeToolAdapter` / `FakePermissionHook`
  / `RecordingAuditHook` / `canonical.py` → 24 passed, 8 skipped.
- [2026-09-10 | qa_engineer] C2 + C3 (commit `bc99011`): red, then
  `sunil/providers/base.py` + `FakeProvider`, `sunil/core/memory/provider.py` +
  `FakeMemoryProvider` → 18 passed / 4 skipped and 18 passed / 1 skipped.
- [2026-09-10 | qa_engineer] OpenAPI suite (17 passed) + C5 conversation-store
  fake (10 passed, 9 skipped) + `.github/workflows/tests.yml` + this file.
- [2026-09-10 | qa_engineer] Handing to the delivery manager for backend review
  of the interface transcription and architect adjudication of finding F-1.

## Issues

Findings from building against the post-fix-round contracts. Severity per the
template: blocker bounces to the responsible engineer; should is fixed or
explicitly accepted here; nit is discretionary. **Nothing below was silently
guessed** — every one names the assumption implemented and, where useful, the
test that pins it so it cannot drift.

### Blocking a Phase 2 stream

- `docs/contracts/C3-memory-provider.md:82-85` — **blocker (Stream C)** — a write
  cannot name its scope. `write(item, rules, *, audit_event_id)` carries no
  scope; `MemoryItem` has no scope field. Yet §2 makes scope a filter "the
  provider must enforce", §4a defines duplicates as content equality "in the SAME
  scope", and §5's own storage shape is
  `list[tuple[MemoryScope, MemoryItem]]`. As frozen, a real Mem0 adapter cannot
  know where to file a write, so §4a and the leak probe of contract test 1 are
  unimplementable against the real signature.
  *Assumption implemented:* the frozen signature is transcribed **unchanged**;
  `FakeMemoryProvider` holds `current_scope` (default
  `MemoryScope(user_id="owner", kind="user", id=None)`) plus a test-only
  `write_in(scope, item, rules, *, audit_event_id)` helper. Pinned by
  `test_c3_write_signature_is_the_frozen_one`, which asserts
  `"scope" not in write.parameters` so the gap cannot drift into an
  implementation unnoticed.
  *Action needed:* contract owner (solution_architect) to choose — a `scope`
  parameter on `write`, a service-side scope binding, or a scope field on
  `MemoryItem` — before Stream C implements C3. This was NOT raised in the
  2026-09-10 QA review (`docs/reviews/2026-09-10-P0-qa-review.md`) and is
  therefore new, not a re-litigated point.

### Should — resolve before the implementations land

- `docs/contracts/C4-approvals.md:164-167` — should — `decide`'s conflict shape
  is "return `state_conflict(...)`" while its success shape is "return row", and
  the unknown-id case is unspecified. *Assumption:* `decide` returns
  `Approval | StateConflict | None`; the HTTP layer maps `StateConflict` → 409
  (§5) and `None` → 404. Stream D builds the dashboard on this shape, so a
  raise-based reading would be a rework.
- `docs/contracts/C1-tool-adapter.md:101-107` — should — §2.1 declares a concrete
  `ToolManager`. Transcribing a concrete class into an interface module would
  ship an importable, non-functional chokepoint that could let a test pass
  vacuously, and the pipeline is production code QA must not write (QA may not
  test its own implementation). *Assumption:* the call shape is transcribed as
  `ToolManagerProtocol` in `base.py`; the concrete `ToolManager` remains
  `core/tool_framework/manager.py`. The name deviation is deliberate and is the
  only one in the transcription.
- `docs/contracts/C4-approvals.md:102` — should — `consume` has no `now`
  parameter, so time must come from inside. *Assumption:* the fake reads its
  injected clock; the real service reads the database clock at the same point.
  `park` advances the shared clock by 1 s, which is how "+1 s per park" is
  realised, and `decide`/`sweep` take `now` explicitly per §6.2/§6.4.

### Nits — recorded for completeness

- `C4 §6.4` — "sweep counts it exactly once" is ambiguous once §6.2 has already
  expired the row lazily at decide time (that sweep legitimately counts zero).
  Implemented and asserted as idempotence on both paths.
- `C4 §6.5` — listing has no method name, signature, unknown-cursor behaviour, or
  stated basis for "id desc". Implemented as
  `list_approvals(*, status=None, limit=50, cursor=None)`; unknown cursor raises
  `ValueError` (the HTTP 422) rather than silently serving page one; the id
  tiebreaker is numeric, never lexicographic — C3 §5 records why (`mem-10` sorts
  before `mem-2` as text).
- `C4 §6` — the in-memory store's attribute name is unspecified → `self.approvals`.
  The injectable clock's type is unnamed → `tests/fakes/clock.py::FakeClock`,
  shared with C3's fixed timestamps.
- `C2 §5` — marker precedence for a message containing two markers is undefined →
  the table's own order (`PLAN:` first). `text` for the plan lane has no specified
  whitespace → compact `json.dumps` separators; tests assert `parsed` equality and
  `json.loads(text)`, never a byte-exact literal the contract does not give.
- `C2 §4` / `C3 §4` — `ProviderError` and `MemoryWriteRejected` are declared as
  attribute sets with no constructor. Added: `ProviderError.__init__` is
  keyword-only with `kind` and `retryable` required (so no call site can
  positionally confuse `kind` with `provider_model`); `MemoryWriteRejected` takes
  `reason` positionally, matching §5's `MemoryWriteRejected(reason=...)` usage.
- `C3 §5` — "`created_at` = `2026-01-01T00:00:00Z` plus `write_index` seconds"
  does not state the base → 0-based, so `mem-1` is exactly the epoch. An empty
  recall query would divide by zero in the scoring rule → empty `RecallResult`.
- `apps/api/pyproject.toml` — `requires-python` is `>=3.12`, the contract floor
  (C1 §2 / ARCHITECTURE_V2 §1), while the toolchain and both CI jobs run 3.13.
  Declaring 3.13 would narrow a frozen contract from a QA file.
- `apps/api/pyproject.toml` — `addopts` carries no `-q`: `ci.yml`'s test job
  already passes `-q`, and two of them raise the quiet level enough to suppress
  the "N passed" summary line, leaving that job with a green tick and no visible
  result. Found by running `ci.yml`'s exact command locally.

### Deferred coverage (22 skipped tests — debt, not passes)

Each skip names its contract test number, the missing production module and its
owner, and prints in CI via the "Deferred coverage (skip reasons)" step.

| Contract tests | Blocked on | Owner |
|---|---|---|
| C1 1–7 (+ ordering probe), 8 skips | `core/tool_framework/manager.py` — the §2.1 pipeline. Bodies are written in full against the frozen signature and activate the moment the module lands. | Stream A / backend |
| C2 2 (schema validation), 3 (retry policy), 5 (router), 6 (Settings), 4 skips | `core/orchestrator/plan_models.py`, `core/routing/retry.py`, `core/routing/router.py`, `sunil/settings.py`. Tests 3 and 6 have real bodies behind an import guard. | Streams B / core |
| C3 6 (service degrade), 1 skip | `core/memory/service.py` — audit-outside-vendor + the 800 ms degrade. The provider-side raise is asserted. | Stream C |
| C5 1–9, 9 skips | `api/routes/chat.py`, `api/deps.py`, `api/schemas.py`, and C5 §4's `StubTurnExecutor` (envelope-shaped, so it cannot precede the envelope models without forking their source of truth). | Stream E / core |

`FakeConversationStore` — C5 §4's route-level fixture — **is** delivered, with its
lane-scoping and blast-radius rules executable now (7 tests), because those rules
are pure data.

### Process note against my own work

`tests/fakes/stub_turn_executor.py` was written before its test — a TDD
violation. Corrected properly rather than papered over: the file was deleted, the
C5 suite was run to confirm it went red on `ModuleNotFoundError`, and the fake was
rebuilt from C5 §4's rules before re-running green. Every other module in this
task followed red-then-green from the start.

## Outcome

- **Commits:** `e01ad5b` (scaffold + C4), `dcf252d` (C1), `bc99011` (C2 + C3),
  plus the OpenAPI/C5/CI/task commit. Branch `task/P0-fakes`, pushed, never
  merged by QA.
- **Test evidence:** 124 collected — **102 passed, 22 skipped** (`pytest -q -m
  "not live"`, i.e. `ci.yml`'s exact command), identical across two consecutive
  runs. No network, no database, no sleeps beyond the 0.05 s timeout probe;
  wall clock 0.33–0.37 s.
  Per contract: C1 24/8, C2 18/4, C3 18/1, C4 15/0, C5 10/9, OpenAPI 17/0
  (passed/skipped).
- **Mutation proof:** letting `FakeApprovalsService.consume` accept an
  already-`consumed` row (single-use broken) produced
  `FAILED tests/contracts/test_c4_approvals.py::test_c4_1_park_decide_consume_is_single_use`
  and the summary `1 failed, 101 passed, 22 skipped`; after
  `git checkout -- apps/api/tests/fakes/fake_approvals.py`, `102 passed, 22
  skipped`. The suite therefore detects the loss of a frozen property rather than
  merely exercising the code.
- **yamllint:** clean on `.github/workflows/tests.yml` against the repo's
  `.yamllint.yml`. No contract or infra YAML was modified.
- **Notes:** the interface transcription needs an independent backend review
  before merge, and finding F-1 (C3 write scope) needs the contract owner. QA
  does not approve its own transcription and has not merged anything.
