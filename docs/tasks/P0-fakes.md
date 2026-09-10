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

## Consolidated update round (2026-09-10, branch `task/P0-fakes`)

One round closing (a) the contract-version migrations the Solution Architect
adjudicated in `docs/tasks/P0-contracts.md` — C3 v1.1.0, C1 v1.1.0, C4 v1.1.0,
C2 v1.0.1 — and (b) every condition from the backend engineer's independent
review of the fakes build. Nothing below was written before its test.

### Contract migration (SA's consolidated delta)

| Item | Landed |
|---|---|
| C3 v1.1.0 — `write(item, rules, *, scope, audit_event_id)` | Seam + fake + all 23 suite call sites; `current_scope`/`write_in`/`DEFAULT_SCOPE`-as-state deleted; the F-1 defect pin replaced by contract test 7's v1.1.0 signature pin (both keyword-only, neither defaulted, `scope` annotated `MemoryScope`) |
| C1 v1.1.0 — `ParkContext`, `adapter_kind \| None`, `execute(..., park_context=)` | Seam; suite tests 1–7 migrated; test 1 probes BOTH `adapter_kind` sides; test 4 asserts `parked[id].continuation/.summary` BY EQUALITY; test 5's continuation calls pass no `park_context`; test 7 re-worded to per-CALL accounting; NEW test 8 (+ a sibling for explicit `park_context=None`) |
| C4 v1.1.0 — fail-closed park material | `ParkRequest.summary` `Field(min_length=1, max_length=500)`, `continuation` `Field(min_length=1)`; `FakeApprovalsService.parked` retention; NEW contract test 8 (three probes) + a legal-minimum guard + a park-retention test; `decide`'s docstring demoted from QA assumption to C4 §6.2 normative |
| C2 v1.0.1 — closed models | `_ClosedModel` base, all five §2 models inherit; NEW contract test 7 (six probes) plus a config-level test so a §2 model added later that forgets the base fails in the suite rather than at the first call site that smuggles a field past it |

`park_ctx` is a FIXTURE, not a module constant: `continuation` is a mutable dict
inside a frozen dataclass, and a shared instance would let one test's edit reach
the next — the F1 lesson (below) applied one seam over.

### Backend-review conditions

| Finding | Disposition |
|---|---|
| **F1** — fakes returned shared mutable module state | **Fixed.** `_usage()` (`model_copy(deep=True)`) and `_plan()` (`deepcopy`) in `fake_provider.py`. `deepcopy`, not `dict(FIXED_PLAN)`: pydantic copies the OUTER dict of a `dict` field but keeps nested values by identity, so a shallow copy still shared `steps[0]["params"]`. Regression test mutates a returned result at three levels (top-level key, nested param, usage field) and asserts the module fixtures AND a second call are untouched — every assertion against a pristine pre-mutation snapshot, because comparing to `FIXED_PLAN` itself is exactly the assertion that passes while both sides rot |
| **F2** — every fake inherited its Protocol, so a missing method silently returned `None` | **Fixed.** No fake inherits its Protocol. Static guard: a module-level `_check: <Protocol> = <Fake>(…)` witness per fake module (`fake_hooks` carries two). Runtime guard: NEW `tests/contracts/test_fake_conformance.py` — Protocol absent from the MRO, every declared member present AND defined in the fake's own class body, async-ness matching, witnesses present with the right annotation, plus one test pinning the hazard itself as executable fact |
| **F5** — 13 of 22 skips were bare `@pytest.mark.skip` on empty bodies | **Fixed.** All 13 now use the C1 import-guard pattern. FULL bodies where the contract specifies enough: C2 test 2's schema clause (whatever `plan_models` exports as `Plan` must validate C2 §5's fixed plan) and C5 test 8 (route-table walk matching `require_service_token` by function IDENTITY through FastAPI's dependency tree — no request, no session, no stub, and it catches the failure a request-level test cannot: a dependency slipped onto a ROUTER). Honest intent-stubs — guard + `pytest.fail` listing the exact assertions — for **C2 test 3 (retry policy), C2 test 5 (router), C3 test 6 (memory service), C5 tests 1, 2, 3, 4, 5, 6, 7, 9**: those rules are frozen but no callable is named, and the C5 route tests additionally need the auth/stub harness whose shape C5 does not fix (session cookie name, whether an ABSENT `Origin` is a mismatch, how the `StubTurnExecutor` is injected). None can sit green having asserted nothing. **Activation proven**, not assumed: with throwaway `sunil/main.py` + `sunil/api/deps.py` stubs, 7 of the 9 C5 tests activated and failed loudly (1–2 correctly stayed skipped on the still-missing `sunil.api.routes.chat`); the stubs were then removed |
| **F6** — uncovered normative areas absent from the debt table | **Fixed** — three rows added below, and the third area (§2.1 step 3's ALLOW-grant burn rule) is now a contract test rather than debt, because it IS testable against these fakes |
| **F8** — two §6.5 pagination readings left loose | **Pinned to the contract's literal words.** `id desc` is LEXICOGRAPHIC (`apr-9` above `apr-10`) — the plain meaning of ordering a string column, and what `ORDER BY created_at DESC, id DESC` will do; C3 §5's numeric rule is not borrowed because C3 states it in words and C4 does not. `next_cursor` is `None` ONLY for a short page, so an exactly-full FINAL page still returns a cursor and the client learns it is done from the following empty page; the look-ahead would have obliged the real service to run a query the contract never specifies. `_park_order` deleted; both readings asserted, and the tiebreak test constructs the tie deliberately because `park` advances the clock 1 s per row |
| **F7** (nit) — a Protocol `__init__` is unverifiable | **Kept as documentation, plus the 4-arg shape test.** A Protocol's `__init__` binds nothing structurally, so its value is documentary — and the test is what keeps the document honest: the parameter list and the absence of defaults (no default audit hook ⇒ "forgot to audit" is not an expressible program) cannot drift inside `base.py` unnoticed |
| **F9** (nit) — `GATEWAY_MODEL_ALIASES` placement + untested; `ToolErrorKind` invented | **Both kept, both now tested.** The alias tuple stays in `providers/base.py` (where the startup parity check will read it) but is asserted against the CONTRACT TEXT, not a copy of the list, so a frozen-namespace change fails here instead of agreeing with a stale constant; mutation-checked (`gpt-mini` → `gpt-nano`: red). `ToolErrorKind`'s membership is pinned to C1 §4's table verbatim — a closed set that exists only in prose cannot be checked, but it must never become a second source of truth |
| **F10** (nit) — empty `conftest.py` | **Deleted, on evidence.** The full suite collects and passes identically without it (145 passed / 25 skipped both ways): `sunil` is installed editable, pytest's prepend import mode already puts `apps/api` on `sys.path` via the tests package boundary, and rootdir comes from `pyproject`'s `[tool.pytest.ini_options]` |

### Deferred coverage — additions (F6)

Extends the table above; same rule, each row names the missing module and its
owner.

| Uncovered normative area | Why it is not testable here | Owner |
|---|---|---|
| **C1 §3 untrusted-results posture** — the 256 KiB per-result cap with `data["truncated"] = true`, and the recursive case-insensitive strip of `instructions`/`system`/`prompt` keys at EVERY nesting depth (lists included) with the removal LOGGED by key path, never silently | All three happen at the MCP adapter boundary / in the context builder, of which nothing exists: there is no MCP adapter (`tool_adapters/mcp_*.py`) and no context block builder. `FakeToolAdapter` is NATIVE, and §3 exempts native results from the cap and strip, so no fake in this repo can exercise them. Note for whoever builds it: §3 calls the strip **cosmetic defence-in-depth** — a key denylist is bypassable by construction and must never be argued as a control, so its test must not be written as a security proof. The load-bearing controls (plan-validated steps only; free-form content cannot reach a privileged action) hold with the strip removed entirely | Stream A (MCP adapters) + core (context builder) |
| **C1 §5 `credential_env:` → `Settings` mapping** — each UPPER_SNAKE entry maps to the lowercased `SecretStr` field, injected into a MINIMAL child env at spawn (never the parent's environment); a name with no matching field, or an unset value, raises `ToolAdapterStartupError` at WIRING time, never a `KeyError` at call time | Needs `sunil/settings.py`, `config/tools.yaml` and the stdio adapter's spawn path. `ToolAdapterStartupError` is transcribed in `base.py` and unraised by anything QA owns; the fail-closed property (a tool that cannot start is ABSENT from the registry, never half-present) is only assertable against real wiring. Two tests to write there: the mapping/redaction round-trip, and a spawned child's env containing exactly the named variables and nothing else | Stream A / backend |
| ~~**C1 §2.1 step 3** — an approval id under an ALLOW grant is ignored, NOT consumed~~ | **No longer debt — tested now.** `test_c1_allow_grant_ignores_an_approval_id_without_burning_it`: parks under ASK_USER, approves, widens the grant to ALLOW, re-executes with the id → `ok=True`, row still `approved`, `consumed_at` still `None`, and the approval is then still consumable. The bug it catches is invisible on the happy path (the call succeeds either way) and expensive: an opportunistic consume burns a single-use approval the owner granted for a different call, and the real continuation then fails `approval_invalid` with nothing to show them | — (was Stream A) |

### Test evidence for this round

- **Before:** 124 collected — 102 passed, 22 skipped. **After:** 170 collected —
  **145 passed, 25 skipped**, identical across two consecutive runs
  (`ci.yml`'s three commands: `-v --strict-markers`, `--strict-markers`, and
  `-q -m "not live"`). +43 passed, +3 skipped. Per contract:
  C1 28/11, C2 31/4, C3 18/1, C4 22/0, C5 10/9, conformance 19/0, OpenAPI 17/0.
- **Mutation proof 1 (re-run, C4 single-use):** letting `consume` accept an
  already-`consumed` row produced
  `FAILED test_c4_approvals.py::test_c4_1_park_decide_consume_is_single_use`;
  reverted, green again.
- **Mutation proof 2 (new, a `ParkContext` property):** making the fake store
  `summary=""` on park. The contract's own `Field(min_length=1)` now makes that
  unreachable through the constructor, so the mutation was applied as
  `req.model_copy(update={"summary": ""})` — validation-skipping, exactly like a
  real service writing the row through an ORM. It produced
  `FAILED test_c4_approvals.py::test_c4_park_retains_the_full_request_for_provenance`,
  and C1 test 4 (the equality assertions) is the same property one seam up,
  skipped only because `manager.py` does not exist yet.
- **Mutation proof 3 (F9 pin):** `gpt-mini` → `gpt-nano` in
  `GATEWAY_MODEL_ALIASES` → red on the contract-text parity test.
- **yamllint:** no YAML was touched this round (the only YAML this task owns is
  `.github/workflows/tests.yml`, unchanged); nothing to re-lint.

### Lessons taken from the review

- **F1 / shared fixtures.** A fake that hands out module-level state is not
  deterministic — it is deterministic until its first caller. Every fake fixture
  is now either immutable or copied per call, and the same reasoning produced
  `park_ctx` as a fixture rather than a constant.
- **F2 / vacuous conformance.** Inheriting a `Protocol` looks like a conformance
  assertion and is the opposite: it fills in whatever the fake forgot with a
  `None`-returning stub. Structural typing plus an explicit witness says the
  same thing without the trapdoor.
- **F5 / self-activating debt.** A skip that cannot notice its own dependency
  arriving is not debt, it is a hole. Import guards make the debt due
  automatically; where the body cannot honestly be written, the guard fails
  loudly with the assertion list rather than passing empty.
