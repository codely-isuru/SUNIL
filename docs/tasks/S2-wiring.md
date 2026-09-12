# S2-wiring — the wave-2 wiring round (backend lane)

**Branch:** `task/S2-wiring` (cut from V2 @`1c2362d`) · **Lane:** backend_engineer · **Date:** 2026-09-12
**Scope owned this round:** all of `apps/api`, plus `config/*.yaml`. Nothing in `docs/contracts/`,
nothing in `tests/contracts/`, `.env.example` untouched (see §7).

The round that makes SUNIL boot for real: every `SUNIL_*=real` seam resolves, the two blocking
security conditions are closed at the wiring, the wave-1 rulings that named this round as applier
are applied, and a governed turn was driven end to end against the real Compose Postgres.

---

## 1. Real seams (`api/wiring.py`, `main.py`)

Wave 1 shipped every implementation and wired none of them: `resolve_*('real')` raised
`SeamUnavailable` naming the owning stream, so the only bootable app was one a test injected.

| seam | real resolution | notes |
|---|---|---|
| **C1** Tool Manager | `build_tool_registry(settings)` → `config/tools.yaml` + `permissions.yaml`, cross-validated (ADR-034); `resolve_tool_manager` returns a **per-plan factory** over the real `ToolManager` with the real `PermissionEngineHook` | the manager is built per plan execution because the audit hook carries ADR-004 Amendment 1's `validated_plan_id` |
| **C2** provider | `providers/wiring.py` — `Settings` → `LaneSettings` (the adapter `registry.py`'s docstring asked for), through `registry.validate_gateway_base_url` (ADR-033) and `validate_direct_base_url` (ADR-017); `ModelCatalogue.load(config/models.yaml)`; `CatalogueRoutedProvider` maps an alias to its registered adapter | lane-invariant: the orchestrator sees one `LLMProvider` and cannot tell gateway from direct. `start()` runs C2 §3's parity check in the lifespan |
| **C3** memory | unchanged — `fake`, injected | Stream C owns the real one; the settings default already says so |
| **C4** approvals | `DatabaseApprovalsService` on the **application's** engine, TTL/grace/notify from `Settings` | a second engine would let the chokepoint park into one database while the dashboard polled another. A `real` selection with no engine is a boot failure |

**A tool that cannot be built is absent, never half-present** (C1 §5, `S-A-tools.md` §4).
`core/tool_framework/wiring.py` builds one adapter per block and returns `(adapters, skipped)`;
every skip is a startup **WARNING** naming the tool and the reason. A missing `GITHUB_TOKEN` must
not take the assistant down — it takes the GitHub tools out of the catalogue, which is the honest
consequence and the safe one (unplannable at layer 4, `unknown_operation` at the chokepoint).
A failed `start()` in the lifespan is the same class of event and gets the same treatment.

`config/projects.yaml` gained `repo: owner/name` (and `ProjectDefinition.repo`): the native GitHub
tool's project→repository mapping. It is config and never a plan parameter — `list_recent_activity`'s
only parameter is `project_key`, which is exactly what stops a plan choosing the repository (M1 T-16).

---

## 2. Security condition **C-1** (HIGH, blocking) — closed

`docs/THREAT_MODEL.md` §9, verbatim: the transactional consume+attempt seam had **zero production
callers**. Fixed at the wiring, as the condition prescribes:

* `core/tool_framework/transaction.py` — `TransactionalApprovals`, the caller the seam never had:
  `park_with_attempt()` parks via `conn=` and writes the attempt row in that transaction (notify
  after commit, C4 §2); `consume_with_attempt()` passes the `attempt_audit` callback and returns the
  audit id **only when the CAS matched**.
* `core/audit/hooks.py` — `attempt_on(conn, record)`: the same row (one shared `_row_values`
  projection), written on the caller's connection, never committed by the hook.
* `manager.py` — both approval paths use it when wired, and **step 4 skips its duplicate exactly
  when the consume transaction already wrote the row**. A failure inside that transaction propagates
  rather than becoming a `ToolResult`: the consume rolls back, so the approval is unspent, and the
  pipeline cannot honestly record an outcome through the audit sink that just failed.
* The seam is **injected, never sniffed**: `api/wiring.py` decides at boot whether the transactional
  path is available (it needs a database C4 service and an audit hook with `attempt_on`). Fakes get
  `transaction=None` and keep the ordering-only posture C1 §6 describes, so the injected-seam path is
  fully unchanged.

**Proving test:** `tests/unit/core/tool_framework/test_chokepoint_transaction.py` — the real manager,
the real `DatabaseApprovalsService` and the real `DbToolAuditHook` on one engine (SQLite **and**
Postgres), with the crash injected exactly where the old window was. Verified red against the old
wiring (`transaction=None`): the two crash tests fail, the other four pass.
`tests/unit/approvals/test_consume_audit_transaction.py` needed no un-skipping — its one skip is the
in-memory-SQLite isolation case, which is a property of the engine, not of the wiring.

---

## 3. Security condition **C-3** (blocking) — closed

`tools/mcp/credentials.py` now checks an explicit **`GRANTABLE_CREDENTIAL_NAMES`** allowlist
(`GITHUB_TOKEN`, `SUNIL_N8N_MCP_AUTH_TOKEN`) **before** the `Settings` lookup, so
`credential_env: [SESSION_SECRET]` — or `SUNIL_SERVICE_TOKEN`, or `DATABASE_URL` — can no longer hand
a spawned child SUNIL's own secrets by a config edit alone. A frozen code constant for the same
reason ADR-033's named-host set is one: a control that can be widened from the environment it
constrains is not a control. The HTTP lane's `auth_token_env` resolves through the same door.
Test names the ungrantable trio: `tests/unit/tools/test_mcp_credentials.py`.

---

## 4. Rulings applied

* **R2** — `db/models.py::Approval` deleted (with its orphaned `ApprovalStatusValue` mirror and the
  false docstring bullet); `db/autogenerate.py` fences `approvals` out of Alembic's comparison on
  **both** sides (`include_name` = the `op.drop_table` the bare deletion would have emitted;
  `include_object` = a future re-add), wired into `env.py`; tests re-pointed
  (`test_db_models.py` now asserts the absence and names where the true shape is pinned), and QA's
  observed workaround in `test_mounted_surface.py` is gone — the full schema is built now that the
  duplicate is.
* **R3 / ADR-008 Amendment 1** — `require_web_client`: an absent `Origin` is a mismatch (403), and an
  unset `app.state.web_origin` refuses rather than waiving the comparison. Blast radius was exactly
  the predicted row: two lane-owned ops suites now send `Origin` on authorised requests.
* **Security LOW hardening** — the ADR-033 lane tripwire gains the `from os import environ` evasion
  and `sunil.settings` to its forbidden sets. Verified by inserting both evasions into a routing
  module (3 tests red), then reverting.
* **R1 follow-up** — `warn_on_ungrantable_catalogue()`: an `agents.yaml` grant naming a tool this
  process did not wire is a startup WARNING naming both sides, never a refusal (the `fake_tool`
  grant is a legal state the ruling preserved).
* **R7 (C4 v1.2.0), parcel 2** — the route's `service_decide` probe, `DECISION_SEAM_MISSING`, the
  `iscoroutinefunction` import and the docstring's 501 row are deleted; `decide_approval` awaits
  `service.decide(...)`. The 501-asserting mounted test is replaced by the full status map
  (200/409/404) through the mounted route on **real** wiring. **Not landed here:** the ruling's
  fake-wired variant and `harness.py:63`, which belong to QA's parcel 1 (the fake's `decide` is their
  file) — asserting an awaitable fake before it is one would go red on a shape nobody has changed.

---

## 5. End-to-end boot evidence

Stack: `scripts/dev-up.sh` (Postgres 17+pgvector, LiteLLM, n8n — all healthy after a
`down -v`; the first attempt failed on stale volumes whose secrets predated the freshly generated
`.env`). `alembic upgrade head` created all ten tables + `alembic_version` in the real Postgres.
API served by `uvicorn` on `127.0.0.1:8123` with `SUNIL_TOOL_MANAGER=real`,
`SUNIL_APPROVALS_SERVICE=real`, `SUNIL_LLM_PROVIDER_LANE=fake`.

* 12 stages in `audit_events`, in order, for one `request_id`;
* the ASK_USER park visible on `GET /api/v1/approvals` behind the real cookie+header+Origin lane;
* decided through the **real** decision route (R7 path) → 200 `approved` by `owner`;
* continuation re-entered through the real chokepoint → approval `consumed`, attempt row in the same
  transaction, exactly one `tool_calls` row per `execute`.

Full paste in the round report. **Two environmental notes, both recorded rather than worked around:**

1. **No provider keys.** `infra/.env.litellm` is absent, so the live-model turn awaits owner-supplied
   provider keys (`docs/SECRETS_SETUP.md`). The model seam ran on C2 §5's `FakeProvider` behind
   otherwise-real wiring; every other seam in the run was production code.
2. **Windows dev host: psycopg-async and MCP stdio cannot share one process.** psycopg 3 refuses the
   `ProactorEventLoop`; `asyncio` subprocesses require it (the same trade-off
   `tests/unit/approvals/conftest.py` already documents for the test suite). So the API ran on a
   selector loop with Postgres real — the MCP child could not spawn, which surfaced as the designed
   `tool_start_failed` WARNING and a `transport_error` on the tool call — and the tool-executing half
   of the continuation was proved on a second leg under the Proactor loop, where the real MCP stdio
   child spawned, completed the handshake and drift check, and returned its result. On the ADR-032
   deployment target (Linux containers) neither constraint exists and one process does both.

The tool used for the evidence is an **MCP stdio fixture server** (scratchpad, not the repo) exposing
`write_item`/`echo`, because the frozen `FakeProvider`'s fixed plan names `fake_tool.write_item` and
neither GitHub tool has a credential in this environment — the licence for that substitution is the
round brief and ruling R1.

---

## 6. Suite

| leg | result |
|---|---|
| SQLite (default) | **946 passed, 4 skipped** |
| Postgres (`SUNIL_TEST_DATABASE_URL` at the Compose database) | **991 passed, 4 skipped** |

The four skips are unchanged from the baseline: one in-memory-SQLite isolation case and three opt-in
live-gateway checks. No lint/type tooling is declared in `apps/api/pyproject.toml` (no ruff, no mypy);
`compileall` is clean and `test_runtime_dependencies.py` (dependency closure) passes.

---

## 7. Findings for other lanes

1. **`scripts/dev-up.sh` leaves `DATABASE_URL` carrying `.env.example`'s template password** while
   generating a fresh `POSTGRES_PASSWORD`, so a freshly generated `.env` cannot connect. The script
   warns about it (`dev-up.sh:144`) and the fix is a hand edit; it is still the first thing a new
   machine hits. `scripts/` is not this lane's file — flagged, not touched.
2. **`localhost` in `DATABASE_URL` blocks on the `::1` candidate** before falling back to IPv4 on
   this host; `127.0.0.1` is immediate. Candidate for `.env.example`'s default (not touched —
   additively or otherwise, this round).
3. **ADR-031's continuation scheduler is still unwired**, so an approved approval does not resume
   itself: the decision route logs the WARNING it was designed to log, and the evidence run drove the
   continuation through the same door the scheduler will use.
4. **Owed, same wave (R7.2):** reconciliation rule 4 in `DatabaseApprovalsService.reconcile_on_startup`
   (`refused`/`expired` + unfinalised task → finalise, + report bucket + test). Named by the ruling as
   a same-wave follow-up; not landed in this round.
5. **DEFECT the evidence run surfaced — a parked turn's envelope carries NO approval id under real
   wiring.** `agents/project_manager/agent.py:182` reads `approval_id` / `expires_at` out of
   `tool_result.data`, and the REAL `ToolManager` returns `data=None` on every error result
   (`manager.py::_error`) — `approval_required` included. The integration double disagrees:
   `tests/integration/tool_manager_double.py:147` returns
   `data={"approval_id": …, "expires_at": …}` on its park path, which is why every integration test
   is green while the shipped behaviour is not. Observed live in this round's run: the
   `final_response` stage detail read `{"outcome": "parked", "approval": "none"}` and C5's
   `TurnApproval.approval_id` is therefore `""` — the dashboard cannot link a parked turn to the
   approval the owner must decide. **Not fixed here**, because the two candidate fixes are not both
   this lane's to choose: (a) the chokepoint returns `data` on an `approval_required` result — a
   change to C1's observable result shape, needing a contract reading of "data is null on an error
   result"; (b) the turn takes the approval ref from the **audited attempt row**, the mechanism the
   spine already uses for the permission decision ("from the audited record rather than from a value
   the agent passed around" — `core/audit/hooks.py`), which needs no contract movement and looks
   right. Raised for the architect + spine lane with the evidence above.
