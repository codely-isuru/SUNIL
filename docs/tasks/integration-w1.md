# integration-w1 — wave-1 merge tree, integration fix round

**Branch:** `task/integration-w1` · **Lane:** backend_engineer · **Date:** 2026-09-12
**Entry state:** 851 passed / 15 failed / 4 skipped (six lanes merged, each green alone)
**Exit state:** 897 passed / 2 failed / 4 skipped — both remaining failures are
QA-owned harness lines in `tests/contracts/`, recorded in §3 with the one-line fix.

The theme of every defect below is the same: **each lane was green alone.** None
of these is a mistake inside a lane. They are all properties that only exist
between two lanes, and no lane's suite could have held them.

---

## 1. Windows event-loop policy collision (10 failures) — FIXED

`tests/unit/conftest.py` session-scoped `WindowsSelectorEventLoopPolicy` across
the whole unit suite (Stream D's half of the merged conftest). psycopg 3's async
mode refuses asyncio's default Windows `ProactorEventLoop`, and
`postgresql+psycopg` is ARCHITECTURE_V2 §5's normative driver (ruling S-1), so
D genuinely needs it — without it the Postgres leg errors out and the
compare-and-swap proof passes on SQLite alone.

But a `SelectorEventLoop` **cannot `subprocess_exec` on Windows**
(`NotImplementedError`, `asyncio/base_events.py:539`), and Stream A's
`tests/unit/tools/test_mcp_stdio.py` spawns a real MCP child over stdio (C1 §5).
Ten of its thirteen tests went red the moment the two conftests were unioned.

**Fix:** relocated, not overridden. The policy now lives in
`tests/unit/approvals/conftest.py` — the only package that reaches Postgres
(`factory.engine_urls()` adds `SUNIL_TEST_DATABASE_URL` to its engine-parametrised
tests; `tests/unit/ops/` and `tests/integration/` are SQLite-only). The
load-bearing docstring travelled with it. `tests/unit/conftest.py` carries a
comment at the old site saying why it must never go back.

Chosen over a proactor-override conftest under `tests/unit/tools/`: two sibling
session-scoped policy fixtures competing for the same default is the shape that
produced this bug, and an override would leave the unit-wide selector policy in
place for every future suite that does not want it.

**Verified:** `tests/unit/approvals` runs on `_WindowsSelectorEventLoop`,
`tests/unit/tools` on `ProactorEventLoop` (probed directly). **CI (Linux) is
unaffected either way** — the default policy there is already selector-based and
the fixture is a no-op.

---

## 2. C6 test 9 route-level auth (5 failures) — 3 FIXED, 2 BLOCKED

### 2.1 The three commissioned stub bodies — written, **QA must re-review**

`test_c6_9_no_session_is_401_on_every_operation`,
`test_c6_9_session_without_the_client_header_is_403_on_every_operation`,
`test_c6_9_service_bearer_without_a_cookie_is_401_on_every_route`.

Bodies written to QA's embedded assertion lists verbatim. **No assertion QA wrote
was changed, and nothing else in `tests/contracts/` was touched.** Two
implementation choices inside the bodies, both flagged for QA:

* The request harness is `tests/ops_harness.py`, deliberately OUTSIDE
  `tests/contracts/` so the diff to the frozen file is exactly the three bodies.
  It is the real `create_app`, the real `POST /api/v1/auth/login` (the cookie is
  minted and signed by ADR-007's machinery, never forged in the test), the real
  dependencies; only the four frozen-contract seams are fakes.
* Clause 3 asserts the bearer case **twice** — bearer alone, and bearer plus the
  browser headers. QA's list says "never 403"; a bearer-only request carries no
  `X-SUNIL-Client`, so "never 403" is only satisfiable if the bearer itself is
  the reason for the refusal. See §2.3.

### 2.2 The routes were never mounted — FIXED (five wiring gaps)

`create_app` mounted health/auth/chat only. Stream D's C4 + C6 routers were only
ever exercised against a hand-built `FastAPI()` in `tests/unit/{approvals,ops}`,
so **the merged application served 404 on every approvals and ops path** and both
lanes stayed green.

| # | Gap | Failure mode if left |
|---|---|---|
| 1 | routers not mounted | 404 on every C4/C6 path |
| 2 | `app.state.ops_engine` unset | `get_engine` raises (by design — an ops route answering `{"tasks": []}` looks like a quiet system) |
| 3 | `app.state.web_origin` unset | Stream D's `require_web_client` **skips** the Origin comparison; ADR-008's CSRF pair silently down to one header |
| 4 | nothing set `request.state.owner_user_id` | every C4/C6 read 401'd behind a valid cookie |
| 5 | Stream D's own `ApiError` class unhandled | 500 on every refusal — an outage where a 401 belongs |

Notes on the choices:

* **Mounted flat** onto `app.router.routes`, like the spine's three.
  `include_router()` on FastAPI ≥ 0.141 records a lazy `_IncludedRouter` and
  `app.routes` then exposes no per-route `dependant`, which silently disarms the
  one audit that bounds the ADR-035 token's blast radius (C5 test 8 / C6 test 9).
  Pinned by `test_routes_are_mounted_flat_so_the_dependency_tree_stays_walkable`.
* **Owner identity** is published by a new `OwnerIdentityMiddleware` from the
  session the spine already signs — a copy, not a second cookie reader. Two
  derivations of "who the owner is" is how they come to disagree. It runs
  innermost because `scope["session"]` does not exist until `SessionMiddleware`
  has run; if it is ever reordered outside, the value is `None` and the route
  refuses (locked door, not open one).
* **Error handler** registered for Stream D's `ApiError` class specifically,
  rather than by calling Stream D's `install_error_handlers` — that function also
  rebinds `RequestValidationError` and would silently re-word the C5-contracted
  422 for the whole app.

### 2.3 Two defects the mount then exposed — FIXED

**`tasks.priority` did not exist.** C6's frozen `Task` shape lists `priority` in
`required` and sources it from `tasks.priority` ("V2 writes 'normal' (M1 schema
default)"). The V2 transcription of `ARCHITECTURE_V1.md` §7.3 into `db/models.py`
dropped it, so every tasks/activity read was `no such column: tasks.priority`
against the real schema. Stream D's suite seeds its own read-model tables, so its
lane could not see it — the mirror image of the `project_key` gap D-be flagged.
Added `NOT NULL DEFAULT 'normal'` + Alembic revision `0003`.

**A bearer-only request to the owner lane answered 403, not 401.** Two frozen
contracts require 401 and neither is satisfied by 403:

* C6 §1 — "a bearer-only request is 401"; §6 test 9 clause 3 — "never 403".
* C5 contract test 5 — `assert approvals.status_code in (401, 404)`, with the
  comment "When Stream D lands, this assertion tightens to `== 401`". Mounting
  the router turned that 404 into a 403 and broke a previously-green contract
  test.

ADR-008's client-header-first ordering produced the 403, because a machine caller
sends no `X-SUNIL-Client`. Reconciled by applying **ADR-035's own rule
symmetrically**: `routes/approvals.py::refuse_service_bearer` refuses a request
that presents an `Authorization` header as unauthenticated, before the CSRF pair
— the machine lane is structurally absent on the owner routes, so the absent lane
is the honest reason for the refusal. 403 would also *say the wrong thing*: it
names the client header as the obstacle and invites the caller to add one, when
no header makes this lane accept a bearer.

The token is **not validated** on that path and never reaches
`deps.require_service_token`, so a real and a forged bearer are indistinguishable
here — no comparison to time, no path on which a valid machine credential is
treated as more interesting.

D-be's pinned CSRF ordering is untouched: with **no** `Authorization` header a
cookie-less request is still 403 before any session logic runs
(`test_routes.py::test_the_client_header_is_checked_before_the_session`), which
is the case ADR-008 exists to cover — a browser cannot set `Authorization`
cross-site.

> **Review ask (D-be + QA):** this changes the refusal code on a request shape
> C5 test 5 and C6 §1 both name. It is the only answer that satisfies both, but
> it is a security-relevant edit to Stream D's module by another lane.

---

## 3. BLOCKED, left red on purpose — `create_app()` takes no arguments

`test_c6_9_no_c6_route_accepts_the_adr_035_service_bearer` and
`test_c6_9_the_five_operations_are_read_only` both call `main.create_app()` with
no arguments. **That call cannot succeed in wave 1, and cannot be made to succeed
without weakening a recorded security control.** Six independent blockers, in the
order they fire:

1. `Settings()` requires `SESSION_SECRET` and there is no repo-root `.env`.
   Giving it a default is explicitly rejected in `settings.py`: "a defaulted
   signing key means every deployment that forgot to set one shares a forgeable
   cookie, silently."
2. `sunil_config_dir` defaults to `./config`, relative to the process's working
   directory — `load_registries` fails wherever pytest was invoked from.
3. `sunil_llm_provider_lane='gateway'` → `SeamUnavailable` (Stream B not plugged
   into `wiring.py`).
4. `sunil_memory_provider='fake'` → `SeamUnavailable`. A `fake` selection
   **requires** an injected seam by `wiring.py`'s rule 1 ("production code never
   imports a test double"), so this one cannot be resolved by configuration at
   all.
5. `sunil_tool_manager='real'` → `SeamUnavailable` (Stream A not plugged in).
6. `sunil_approvals_service='real'` → `SeamUnavailable` (Stream D not plugged in).

Per the round's protocol — *if an assertion cannot be satisfied without bending
the contract, stop and record it rather than bend it* — these two are left red
with this note rather than edited. The **assertions** in both are correct and
valuable; only the harness line is wrong.

**The fix is QA's and it is one line in each:** build the app the way C5 contract
test 8 already does in the same suite (`test_c5_chat.py::_route_table_app()` —
explicit `Settings(...)` + `Seams(...)`, no database traffic, no request).

**Both properties are defended in the meantime.** `tests/unit/test_app_wiring.py`
runs the identical route-table walks over a properly-constructed app:

* `test_no_c6_or_c4_route_accepts_the_adr_035_service_bearer` (also covers C4)
* `test_the_five_c6_operations_are_mounted_and_get_only`

So a regression fails the suite today; QA's harness fix only moves the evidence
back into the contract file where it belongs.

---

## 4. ApprovalSweeper wired into the app lifespan — DONE

Stream D left the seam explicitly (`docs/tasks/S-D-approvals.md` §5: "`start()` /
`stop()` are the seam"). `create_app` now builds an `ApprovalSweeper` over the
resolved C4 service, starts it in the lifespan before the first request, and
stops it on shutdown **before** the engine is disposed (a tick holding a
connection into `engine.dispose()` is an error line on every restart).

Kill switch `SUNIL_APPROVALS_SWEEPER_ENABLED`, **default ON** — the safe posture
is the one an operator gets by doing nothing. Off means *not started*, not
"started and idle": `reconcile_on_startup` is a state transition, so a kill
switch that still reconciled would be a kill switch that still changed rows.

A resolved C4 service with no schedule (C4 §6's fake has `sweep(now)` and no
`reconcile_on_startup`) does not stop the app booting, but is logged at
**warning** naming the consequence. The two `None` cases are not the same thing
and are not logged the same way.

Seven tests in `tests/unit/test_app_sweeper_lifespan.py`.

---

## 5. Open items for the next round (found, not fixed — out of this round's scope)

1. **Two Alembic heads.** `20260911_1200_d4_approvals_table.py` declares
   `down_revision = None` and a branch label, as D-be documented it would until
   the spine's initial revision existed. It exists (`0001`). `alembic upgrade
   head` now has two heads to choose between, so **a fresh deployment cannot
   migrate**. Fix is one line (`down_revision = "0003"`, drop the branch label)
   but it wants a verified Postgres run, which this environment has none of.
2. **`task_status_events.id` type disagreement.** `ops_read_model.py` declares it
   `Integer autoincrement`; `db/models.py` declares `String(36)` UUID. The detail
   route tiebreaks `ORDER BY at ASC, id ASC` and its comment reasons from "a
   table whose id is a monotonic integer". Against the real schema that tiebreak
   is stable but arbitrary, not write order. Not a crash and no test fails; C6
   §2.2 only requires ascending `at`. Same disagreement on `audit_events.id`,
   which no route orders by.
3. **`wiring.py` still refuses every `real` seam.** Streams A, B and D have all
   landed their implementations; `resolve_provider` / `resolve_tool_manager` /
   `resolve_approvals` still raise `_unbuilt`. The app therefore boots only with
   injected seams — i.e. only in tests. This is the next round's main job and it
   is the reason §3 exists.

---

## 6. Evidence

```
Full suite, run twice, identical:
  897 passed, 2 failed, 4 skipped        (entry: 851 passed, 15 failed, 4 skipped)

The 2 failures: §3 above, both QA-owned harness lines.
The 4 skips, all legitimate and pre-existing:
  tests/unit/approvals/test_consume_audit_transaction.py:116
      — in-memory SQLite StaticPool shares one connection (needs the Postgres leg)
  tests/unit/providers/test_gateway_live.py:55, :81, :109
      — live gateway check, opt-in via SUNIL_LIVE_GATEWAY_TEST=1 with the dev stack up
```
