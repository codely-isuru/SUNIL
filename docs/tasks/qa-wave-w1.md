# qa-wave-w1 — wave-1 review of the integrated tree

**Branch:** `task/qa-wave-w1` (from `task/integration-w1`) · **Lane:** qa_engineer · **Date:** 2026-09-12
**Verdict: PASS-with-conditions** — one blocker (B1) must close before the wave is
called done. Everything else is a should/nit and can be scheduled.

Base `b1a5125`; pulled `cafc6e4` (the backend lane's Alembic + id-type round) near the
end and re-ran everything. Counts below are post-pull unless stated.

---

## 1. Counts (every run done twice, identical both times)

| Leg | Before my fix | After my fix (base) | After pulling `cafc6e4` |
|---|---|---|---|
| `apps/api`, SQLite only | 897 P / **2 F** / 4 S | 899 P / 0 F / 4 S | **901 P / 0 F / 4 S** |
| `apps/api`, + Postgres leg | — | 938 P / 0 F / 4 S | **940 P / 0 F / 4 S** |
| `apps/web` `pnpm test` | — | 38 P / 0 F (5 files) | **38 P / 0 F** |
| `apps/web` `pnpm build` | — | exit 0, 13 routes | **exit 0** |

Postgres leg: a throwaway `postgres:17` on `127.0.0.1:55444`, password generated from
the OS CSPRNG in-process and never written to the repo. The `[postgresql+psycopg]`
parametrisation is real — 39 extra tests ran, including the three CAS-race proofs.

The 4 skips are legitimate and unchanged: one needs a non-StaticPool connection
(`test_consume_audit_transaction.py:116`) and three are the opt-in live-gateway probes.

---

## 2. Part 1 — the two red harness lines, fixed

`test_c6_9_no_c6_route_accepts_the_adr_035_service_bearer` and
`test_c6_9_the_five_operations_are_read_only` called `main.create_app()` bare, which is
unbuildable by design (integration-w1 §3). Both now build the app through
`tests/ops_harness.py::build_ops_app()` — the shared form of
`test_c5_chat.py::_route_table_app()`, and the same one `tests/unit/test_app_wiring.py`
already walks, so the contract clause and the wiring test see one application rather
than two. **No assertion was changed**; `git diff` on this file is exactly the two
harness lines plus their comments.

The second test was wrong twice over: `ops_lane` returns a **list** when given two
module names, so its `hasattr(main, "create_app")` was always False and the fallback
branch made the bare call anyway. Recorded in the replaced line's comment.

The bearer walk is now built with the machine lane **ON** (`service_token=`), so it
cannot pass for the wrong reason.

### Mutation proof (both fixed clauses are load-bearing)

| Mutant | Result |
|---|---|
| `require_service_token` added as a **router-level** dependency on `tasks.py` | `test_c6_9_no_c6_route_accepts_the_adr_035_service_bearer` FAILED |
| `POST /api/v1/tasks` added to the tasks router | `test_c6_9_the_five_operations_are_read_only` FAILED |

Both mutants reverted; `git status` clean apart from this file.

---

## 3. Part 2 — author-is-asserter re-review inside QA's files

### 3.1 The three completed C6 test-9 stub bodies — **ACCEPTED**

Each body is QA's embedded assertion list verbatim, and each is load-bearing against a
single-point mutant of the production control it grades:

| Mutant (in `routes/approvals.py`) | Clause that caught it | Nothing else failed |
|---|---|---|
| `refuse_service_bearer` dropped from `require_owner_lane` | clause 3 — bearer-only got `403 forbidden_client` | ✓ |
| `require_owner_session` made to fail open | clause 1 | ✓ |
| client header accepted if merely non-empty | clause 2 (its `X-SUNIL-Client: curl` half) | ✓ |

**Choice 1 — `tests/ops_harness.py` outside `tests/contracts/`: accepted.** It keeps the
diff to the frozen file to exactly the three bodies, and it gives the contract clauses
and the wiring tests one definition of "a signed-in owner". Recorded risk (nit N1): a
frozen contract file now depends on a module the implementation lane owns, so the
meaning of clause 1 could be changed without touching the contract file. The property
holds by construction today (`sign_in=False` makes no login call, so the jar is empty)
and is indirectly pinned by `test_app_wiring.py::test_stream_ds_error_envelope_...`.

**Choice 2 — clause 3 asserts the bearer case twice: accepted, with a correction to the
stated reason.** Sub-case A (bearer alone) is the one that carries ADR-035's "the lane
never returns 403" — it is what caught the mutant above. Sub-case B (bearer + browser
headers) is **defence in depth, not a second reading of the contract**: no single-point
mutation makes B fail while A passes. It is additive beyond QA's list, contradicts no
clause, and forecloses "a bearer becomes a valid owner credential once the CSRF pair is
satisfied", so it stays.

Checked against the sources, not against the lane's summary: C6 §1 ("a bearer-only
request is 401"), C6 §6 test 9, and ADR-035 Decision ("401 on bad/missing token; the
lane never returns 403" + "contract test 5 probes the structural scope").

### 3.2 Stream B's two self-activated C2 bodies — **ACCEPTED**

`test_c2_3_sunil_retry_policy_re_asks_exactly_once` and
`test_c2_5_local_only_routes_nowhere_without_a_local_provider`. Both are QA's
commissioned lists faithfully, and both are load-bearing:

| Mutant | Result |
|---|---|
| `MAX_ATTEMPTS_BY_KIND["invalid_output"]` 2 → 3 | C2 test 3 FAILED |
| the `LOCAL_ONLY and not provider_entry.local` guard short-circuited | C2 test 5 FAILED |
| A-2 usage totalled over the successful attempt only | C2 test 3 FAILED |

Two judgements:

* The hand-rolled `_AlwaysInvalidOutput` double **is necessary**. Verified against the
  frozen fake: C2 §5's `FAIL:invalid_output` marker uses an instance counter and
  succeeds on the second call by design, so it cannot express "raises on every call" —
  which is the second half of QA's own commissioned assertion.
* The extra `outcome.usage.input_tokens == 2 * FIXED_USAGE.input_tokens` assertion is
  additive and correct: C2 §4's `usage` comment is normative ("tokens burned by failed
  attempts still count (M1 A-2 rule)"), and the mutant above proves it grades something.

Weakness recorded (nit N2): C2 test 5's `pytest.raises(RoutingError)` asserts no
kind/message, so an unrelated routing failure would satisfy it. Adequately guarded by
the INTERNAL-request half in the same body, which is exactly why QA's list demanded it.

### 3.3 The spine's additive edits — claim **VERIFIED**

The claim was "no QA assertion changed". Checked by diffing `dd18210..b1a5125` over all
of `tests/contracts/` and `tests/fakes/` and filtering every removed line containing
`assert`: **every one is inside a `pending(...)` string** (the commissioned assertion-list
text), not an executable assertion. Nothing else was deleted.

* `test_c5_chat.py` — the nine `pending()` placeholders became bodies; the harness block
  is new; `_route_table_app()` is the same fix I made for C6.
* `test_c3_memory_provider.py` — clauses (a)/(b)/(c) as commissioned, plus a
  healthy-provider control that stops (a) being the service's only behaviour. Good.
* `stub_turn_executor.py` — purely appended; `FakeConversationStore` and
  `ConversationNotFound` are byte-identical. The six behaviours match C5 §4's table
  row-for-row, including `task=null` on `FAILP:`/`REJECT:`/`NOPROJ:`.

---

## 4. Part 3 — wave review

### 4.1 Findings

#### B1 — BLOCKER · the mounted C4 approvals surface answers **500 to an authorised owner**

`apps/api/sunil/api/routes/approvals.py:266` (and `:290`, and the decision route).

Reproduced independently against the merged app over ASGI, with a real cookie minted by
`POST /api/v1/auth/login`, both before and after `cafc6e4`:

```
AUTHORISED OWNER (cookie + X-SUNIL-Client: web + Origin)
  GET   /api/v1/approvals                  -> 500   TypeError: object ApprovalListResponse
                                                    can't be used in 'await' expression
  GET   /api/v1/approvals/apr-1            -> 500
  POST  /api/v1/approvals/apr-1/decision   -> 500
  GET   /api/v1/tasks                      -> 200   {"tasks":[],"next_cursor":null}
  GET   /api/v1/activity                   -> 200
  GET   /api/v1/audit                      -> 200
```

**Root cause — the seam is wider than the contract that governs it.** C4 §4 and its
transcription `sunil/core/approvals/base.py::ApprovalsService` declare exactly two
methods, both async: `park` and `consume`. The HTTP surface calls and awaits four more —
`list_approvals`, `get`, `decide`, `sweep` — which the Protocol never declares. C4 §6's
frozen fake implements `decide`/`sweep`/`list_approvals` **synchronously** and has no
`get` at all, which is conformant with the Protocol as frozen; `DatabaseApprovalsService`
implements them async. So **any contract-conformant service 500s on all three C4 routes.**

Why nothing caught it: Stream D's `tests/unit/approvals/test_routes.py` mounts the
router against the real async service on a hand-built app, and every approvals request in
`tests/unit/test_app_wiring.py` probes only the **refusal** paths (401/403). The
equivalent C6 assertion exists — `test_the_ops_read_engine_is_wired_to_the_applications_database`
drives `GET /api/v1/tasks` to 200 — so the gap is an oversight, not a decision.

Why it matters now rather than later: `wiring.py` still refuses every `real` seam
(integration-w1 §5.3), so the fake wiring is the **only configuration the app can
currently boot in**, and in it the approvals queue does not work. "An unmounted approval
queue is an owner who cannot approve anything" is this round's own stated reason for
mounting the router.

**Action (Stream D / backend_engineer, with an architect ruling on the contract):**
1. Decide the seam shape — the natural answer is to widen C4 §4's Protocol to the six
   methods the route actually uses, all async, and version C4.
2. Make `tests/fakes/fake_approvals.py` match whatever is ruled. *That file is QA's; I
   have not changed it, because changing the fake to match the caller before the contract
   is ruled is how a fake stops being evidence.*
3. Add the missing authorised-path test — `GET /api/v1/approvals` → 200 through
   `create_app`, the mirror of the C6 one that already exists.

#### S1 — should · three settings are in no inventory (`SUNIL_APPROVALS_SWEEPER_ENABLED` among them)

Swept every `Settings` field against `.env.example` and `ARCHITECTURE_V2` §5, whose
heading claims "complete — every variable and port the system needs":

| Field | `.env.example` | ARCH §5 |
|---|---|---|
| `SUNIL_APPROVALS_SWEEPER_ENABLED` | **absent** | **absent** |
| `SUNIL_TOOL_MANAGER` | **absent** | **absent** |
| `SUNIL_APPROVALS_SERVICE` | **absent** | **absent** |
| every other field (24) | present | present |

Answering the brief's question directly: **no, `SUNIL_APPROVALS_SWEEPER_ENABLED` is not
in `.env.example`.** It is a kill switch for a job that performs state transitions, added
this round (`settings.py:229`, `main.py:223`), and an operator cannot discover it. The
other two are seam selectors; both default to `real`, which is the right default, so this
is a documentation gap and not a posture one. `ANTHROPIC_*`/`OPENAI_*` are absent from
`.env.example` **deliberately** (they live in `infra/.env.litellm.example`) and are not
counted here. Owner: integration lane + architect.

#### S2 — should · production config grants a test-only tool

`config/agents.yaml` grants `project_manager` the operations `fake_tool.echo` and
`fake_tool.write_item`. `fake_tool` is C1 §6.3's **contract fake**; it appears in neither
`config/tools.yaml` nor `config/permissions.yaml`. Asked the real engine:

```
project_manager.fake_tool.write_item  -> deny  (no grant for this triple (default deny))
project_manager.fake_tool.echo        -> deny
project_manager.github.list_recent_activity -> allow
```

Fail-closed, so not a security defect — but a deployed SUNIL can *plan* a call that the
chokepoint then always denies, i.e. a turn that fails late instead of at plan validation.
Nothing cross-validates `agents.yaml` grants against `tools.yaml` (`load_registries` reads
only `agents.yaml` + `projects.yaml`; the tools↔permissions cross-check at
`tools_config.py:190` does not cover this direction).

The grant is **load-bearing**: removed it and `tests/integration` went 9 failed / 4 passed,
because that suite points `SUNIL_CONFIG_DIR` at the repo's real `config/`. So this is a
real design tension, not a stray line — it wants a ruling (a test-only overlay config, or
a documented production grant), not a quiet deletion. Owner: spine lane + architect.

#### N1, N2 — see §3.1 and §3.2.

#### N3 — nit · `pnpm test run` fails with "No test files found"

`package.json`'s script is already `vitest run`, so the extra `run` is parsed as a
**name filter** and matches nothing: exit 1, zero tests. `pnpm test` is correct (38 pass).
Worth fixing in one direction or the other before someone "fixes" it with
`--passWithNoTests`, which turns a loud failure into a silent zero-test pass.

#### N4 — nit · stale path in a docstring

`apps/api/tests/unit/test_app_wiring.py:8` says the payload laws are graded in
`tests/unit/ops/test_c6_ops_reads.py`; the C6 contract suite is
`tests/contracts/test_c6_ops_reads.py`.

### 4.2 Cross-lane value sweep — everything else agrees

| Sweep | Result |
|---|---|
| Gateway aliases: `infra/litellm/config.yaml` `model_list` vs `config/models.yaml` `models:` | **match**, 5/5 — `claude-haiku, claude-opus, claude-sonnet, gpt-flagship, gpt-mini` |
| `capabilities:` → `models:` references | all resolve |
| `models:` → `providers:` references | all resolve |
| `permissions.yaml` tools vs `tools.yaml` | `github`, `github_mcp`, `n8n_mcp` — match |
| `agents.yaml` grants vs `tools.yaml` | **`fake_tool` unmatched** — S2 |
| Ports: compose vs `.env.example` vs ARCH §5 | 5433 / 4000 / 5680 / 8000 / 3001 — all agree |
| Every compose publish bound to `127.0.0.1` | yes, 3/3 |
| `.env.example` application vars with no `Settings` field | none |
| `Settings` fields absent from the inventories | 3 — S1 |

### 4.3 Exit criteria — each lane's headline claim, verified by running it

| Lane | Claim | Evidence |
|---|---|---|
| S-spine | 12-stage governed turn | `tests/integration` **13/13 passed**, incl. `test_the_turn_writes_all_twelve_stages_in_order` |
| S-A | ALLOW does not burn an approval | `test_c1_allow_grant_ignores_an_approval_id_without_burning_it` PASSED |
| S-B | gateway parity + lane tripwire | `test_start_refuses_to_boot_when_an_alias_is_missing`, `test_start_accepts_a_gateway_serving_every_catalogue_id`, and 13 tripwire tests incl. `test_the_tripwire_has_something_to_guard` (non-vacuous) — 60 passed |
| S-D (be) | CAS race on Postgres | 3 CAS tests + 4 consume-audit tests ran and passed under `[postgresql+psycopg]` |
| S-D (web) | build + tests | `pnpm build` exit 0 (13 routes); `pnpm test` 38/38, twice |
| integration | routers mounted and wired | C6 yes (three 200s); **C4 no — B1** |
| integration `cafc6e4` | one Alembic head | verified on a **fresh Postgres**, below |

### 4.4 The 403 → 401 owner-lane change — verified behaviourally

Driven against the merged app, not read off the lane's own tests. Full credential ×
route matrix (5 C6 paths + 2 C4 paths):

| Credential shape | Answer on all 7 routes |
|---|---|
| valid bearer, no cookie | **401 `unauthenticated`** |
| forged bearer, no cookie | **401 `unauthenticated`** (indistinguishable from valid — no oracle) |
| bearer + `X-SUNIL-Client: web` + Origin | **401 `unauthenticated`** |
| no cookie, no client header | 403 `forbidden_client` (ADR-008 ordering intact) |
| no cookie, client header ok | 401 `unauthenticated` |
| cookie + `X-SUNIL-Client: curl` | 403 `forbidden_client` |
| cookie + hostile `Origin` | 403 `forbidden_client` |
| cookie + browser headers (the 200 path) | 200 on the three C6 routes; **500 on the three C4 routes — B1** |

ADR-035's "the lane never returns 403" holds: **zero** requests carrying an
`Authorization` header met a 403. Behaviour matches C6 §1, C5 test 5's recorded
tightening, and ADR-035. Design review of the change is Security's, not mine.

### 4.5 The pulled Alembic fix — independently verified on real Postgres

integration-w1 §5.1 said the fix "wants a verified Postgres run, which this environment
has none of". It has one now:

```
alembic heads                        -> 0004 (head)          [one head, was two]
alembic upgrade head (FRESH db)      -> exit 0, 11 tables
alembic current                      -> 0004 (head)
alembic downgrade base               -> exit 0, only alembic_version remains
alembic upgrade head (again)         -> exit 0, 0004 (head)   [round trip clean]

tasks.priority            character varying(20) NOT NULL DEFAULT 'normal'
tasks.project_key         character varying(100), ix_tasks_project_key btree
task_status_events.id     integer generated by default as identity   [monotonic]
```

A fresh deployment can migrate, and the detail route's `ORDER BY at, id` tiebreak is now
write-order as its comment claims. §5.1 and §5.2 of integration-w1 are closed.

---

## 5. Verdict

**PASS-with-conditions.**

Condition to close before the wave is done: **B1**. A mounted surface that answers 500 to
the authorised owner, in the only configuration the application can boot in, is not a
shipped surface — and the contract under-specification behind it will produce the same
class of bug again if it is patched at the fake instead of at the Protocol.

Schedule, do not block on: S1, S2, N1–N4.

Everything else in this wave holds up under adversarial probing: the auth posture is
right on all seven owner routes, the ADR-035 blast radius is bounded structurally and at
request level, the twelve-stage turn runs, the CAS survives a real Postgres race, the
config values agree across five files, and the migration chain now applies to a fresh
database and rolls back cleanly.

## 6. Boundaries observed

Changed exactly one file of production-adjacent code: `tests/contracts/test_c6_ops_reads.py`
(two harness lines), plus this document. Every mutant used as evidence was reverted and
`git status` re-checked each time. No production code, no `apps/web` source, no other
lane's tests, and no fake were modified — including `tests/fakes/fake_approvals.py`, which
B1 touches but which must not be reshaped until the contract is ruled.
