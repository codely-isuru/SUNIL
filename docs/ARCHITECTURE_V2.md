# SUNIL V2 — Rebuild Architecture

**Status:** Proposed (Architect, Phase 0) · **Date:** 2026-09-10 · **Branch:** `V2`
**Basis:** ADR-030 + Amendment 1 (clean-slate rebuild; `main` is the M1 reference, not a
dependency) · `V2_DEVELOPMENT_PLAN.md` (phases/streams) · `V2_INTEGRATION_ROADMAP.md` (components)
**Contracts:** [`contracts/C1-tool-adapter.md`](contracts/C1-tool-adapter.md) ·
[`contracts/C2-model-provider.md`](contracts/C2-model-provider.md) ·
[`contracts/C3-memory-provider.md`](contracts/C3-memory-provider.md) ·
[`contracts/C4-approvals-openapi.yaml`](contracts/C4-approvals-openapi.yaml) (+
[rationale](contracts/C4-approvals.md)) ·
[`contracts/C5-chat-openapi.yaml`](contracts/C5-chat-openapi.yaml) (+
[rationale](contracts/C5-chat.md))
**New decisions:** ADR-031 … ADR-035. **Non-negotiables honoured:** ROADMAP §25 (structured output
for privileged decisions), §26 (twelve security rules), §33 (twelve design rules).

Deviations from M1 shapes, all in one place (house convention): the §6 envelope gains
`outcome=parked` + `approval` (ADR-031); `ToolAdapter` gains `kind` + `start()/stop()` (C1 §2);
provider transport defaults to the LiteLLM gateway lane (ADR-033); auth gains the machine-caller
lane on one route (ADR-035). Everything else keeps M1's proven shape.

**Fix round 2026-09-10** (QA + Security reviews of the same date): §4/§5/§6 reconciled to the real
host ports — **web 3001, postgres 5433, n8n 5680** (ADR-032 Amendment 1; QA B6 = Security B1);
compose path corrected to `infra/docker-compose.yml`, image pins recorded, profiles deferred;
`SUNIL_APPROVAL_CONSUME_GRACE_HOURS` added (C4 grace-bounded consume, Security item 1); §3's C1
seam wording follows ADR-031 Amendment 1.

---

## 1. Stack and shape

**FastAPI (Python ≥ 3.12) + SQLAlchemy 2 async + Alembic on PostgreSQL 17 + pgvector; Next.js 16
web app; httpx for every outbound call (no provider SDKs).** This is the ROADMAP §4 direction and
the M1-verified stack; no ADR argues otherwise. What changes from M1 is the database default —
Postgres from day one (the Compose `postgres` service exists anyway for LiteLLM/n8n; ADR-001's
"one portable schema" is kept, so SQLite remains usable for unit tests via the same models).

## 2. Module layout (rebuilt `apps/api/sunil/`)

M1's layout survived a full build, a security review and two follow-on milestone designs; the
rebuild keeps it and adds exactly the packages the six streams own. The import law is unchanged
and re-enforced by a tripwire test: **`core/` never imports `sunil.api`**; `providers/`, `tools/`,
`memory_providers/` never import `core/orchestrator`.

```
apps/api/sunil/
  settings.py                  # single env seam; ADR-017 + ADR-033 validators; SecretStr
  main.py                      # create_app(settings) factory (ADR-018)
  api/
    deps.py                    # require_owner_session, require_client_header, require_service_token (ADR-035)
    middleware.py              # CORS (WEB_ORIGIN), session
    schemas.py                 # C5 envelope models (generated-checked against C5 OpenAPI)
    routes/{auth,health,chat,approvals,conversations,projects}.py
  core/
    orchestrator/              # turn.py (run_turn + run_continuation, ADR-031), plan_models,
                               # plan_validator (§25: constrained decode → Pydantic → registry re-check)
    agent_framework/           # base + runner (agents are roles, §33.4)
    tool_framework/            # C1: base.py, manager.py (the chokepoint)
    permissions/               # engine.py — M1 shape verbatim (structural default-deny)
    approvals/                 # C4: service.py (park/consume/decide), sweeper.py, notify.py
    memory/                    # C3: provider.py (protocol), service.py (audit-outside-vendor), short_term.py
    routing/                   # C2: router.py (capability × privacy policy — SUNIL-owned)
    registry/                  # config/*.yaml loaders (agents, models, tools, permissions, projects)
    conversations/  tasks/  workflows/  trace/  audit/
  providers/                   # C2 impls: gateway.py (LiteLLM lane), anthropic.py, openai.py (direct lane)
  tools/                       # C1 impls: native/github/, mcp/stdio.py, mcp/http.py (Stream A)
  memory_providers/            # C3 impls: mem0_provider.py (Stream C)
  agents/                      # project_manager/, developer/ (OpenHands delegate, Stream F)
  db/                          # models.py, session.py, capture.py; alembic/
apps/api/tests/
  fakes/                       # THE Phase 0 deliverables: fake_tool_adapter, fake_provider,
                               # fake_memory_provider, fake_approvals, stub_turn_executor
  contracts/                   # test_c1..c5 — the suites every stream must keep green
apps/web/                      # Next.js 16: chat, dashboard (approvals queue, agent activity, audit browser)
config/                        # mounted, never baked (ADR-016): models.yaml, agents.yaml,
                               # tools.yaml (ADR-034 server blocks), permissions.yaml, projects.yaml
infra/docker-compose.yml       # ADR-032 Amendment 1: compose lives under infra/ (with postgres/,
                               # litellm/ config); `infra`/`full` profiles deferred until the api
                               # container exists
```

**§2 Amendment 1 (2026-09-11 — C6 ops reads; owner Gate 2 ruling Q1 = freeze, ADR-036).**
`api/routes/` gains three read-only modules serving the dashboard's operational views
(`V2_DASHBOARD_SPEC.md` §7/§8/§10/§16), contracted in
[`contracts/C6-ops-reads.md`](contracts/C6-ops-reads.md) (+ OpenAPI):

| Route | Module | Operations | Contract |
|---|---|---|---|
| `GET /api/v1/tasks`, `GET /api/v1/tasks/{task_id}` | `api/routes/tasks.py` | task list (status/project_key/q/order filters, C4-law cursor paging) + detail with `status_events` | C6 §2.2 |
| `GET /api/v1/activity` | `api/routes/activity.py` | one-request running/parked/recent(≤20) snapshot with latest audit stage folded in | C6 §2.3 |
| `GET /api/v1/audit`, `GET /api/v1/audit/{request_id}` | `api/routes/audit.py` | turns grouped by `request_id` + per-turn `events`/`approval_events` partition | C6 §2.4 |

All three are **read-only, owner-session only** (the C4 cookie + `X-SUNIL-Client` lane; the
ADR-035 bearer is never valid here). Companion schema delta: `tasks.project_key` nullable column
(C6 §3, Q2 ruling). The original layout block above is unchanged per the no-silent-edit
convention; read its `routes/{…}` line as including `activity`, `tasks`, `audit`. QA fake:
`tests/fakes/fake_ops_store.py` + contract suite `tests/contracts/test_c6_ops_reads.py` (C6 §6).

## 3. How the six streams plug into the contracts

| Stream | Builds | Implements / consumes | Tests against |
|---|---|---|---|
| A — MCP tools | `tools/mcp/{stdio,http}.py`, config server blocks | **implements C1**; consumes C4 via the injected `ApprovalsService` seam (C1 §2.2) | `FakeApprovalsService`, contract suite C1 |
| B — Model gateway | `providers/gateway.py`, LiteLLM container config | **implements C2** behind the SUNIL router | `FakeProvider` parity + loopback LiteLLM double (ADR-017 seam) |
| C — Memory & entities | `memory_providers/mem0_provider.py`, entity tables, `core/memory/service.py` | **implements C3**; embeddings via C2 | `FakeMemoryProvider`, contract suite C3 |
| D — Approvals & dashboard | `core/approvals/*`, `api/routes/approvals.py`, web dashboard pages | **implements C4**; renders C5 `parked` | `FakeApprovalsService` behind the real routes; C4 suite |
| E — n8n workflows | n8n container, trigger + MCP-server workflows | **consumes C5** (ADR-035 lane); exposes tools consumed via C1/`mcp_http` | `StubTurnExecutor` behind the real chat route |
| F — OpenHands dev agent | `agents/developer/`, OpenHands container | consumes C1 (its git ops are tool calls) + C4 (`merge_main: ask_user`) | C1/C4 fakes |

Phase 2 replaces fakes with implementations in the plan's plug order; the contract suites in
`apps/api/tests/contracts/` are the merge gate ("nothing merges without its contract tests passing
against the fakes").

## 4. Trust boundaries

| TB | Boundary | Crossing | Controls (each named in §5's inventory) |
|---|---|---|---|
| TB1 | browser → API | `http://localhost:3001` page → `http://localhost:8000` XHR/fetch (web on 3001 — ADR-032 Amendment 1) | signed session cookie (`SESSION_SECRET`, ADR-007); CORS allow-list = `WEB_ORIGIN`; `X-SUNIL-Client: web` + Origin check (ADR-008); Pydantic 422 wall |
| TB2 | API → LiteLLM | `SUNIL_LLM_GATEWAY_BASE_URL` (`http://localhost:4000`) | ADR-033 URL validator; per-agent virtual key (`LITELLM_VIRTUAL_KEY_*`, budgets in LiteLLM); redaction registry keeps secrets out of prompts; router privacy policy upstream of transport |
| TB3 | LiteLLM → cloud providers | `api.anthropic.com` / `api.openai.com` | provider keys live ONLY in the litellm container env; SUNIL app env carries none in gateway lane |
| TB4 | API → MCP stdio child | spawned subprocess, JSON-RPC on pipes | minimal child env (only `credential_env` names, C1 §5); params validated pre-send; results untrusted + size-capped (C1 §3); `timeout_s` |
| TB5 | API → MCP HTTP (n8n) | `SUNIL_N8N_MCP_BASE_URL` (`http://localhost:5680/mcp` — ADR-032 Amendment 1) | ADR-033 validator; n8n-side auth header from settings; same untrusted-results posture |
| TB6 | MCP server / n8n → upstream SaaS | GitHub, Gmail, Stripe, WordPress… | least-privilege credentials held in the server/n8n vault, never in agents (ADR-030 rule); pinned server versions (ADR-034 drift check) |
| TB7 | n8n → API | `http://localhost:8000/api/v1/chat` | `SUNIL_SERVICE_TOKEN` bearer (ADR-035), constant-time compare, route-scoped; audit `channel="service"` |
| TB8 | API → n8n webhook | `SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL` | ADR-033 validator; redacted summary payload only (C4 §2); fire-and-forget |
| TB9 | API/LiteLLM/n8n → Postgres | host `localhost:5433`; in-network `postgres:5432` (ADR-032 Amendment 1) | three databases, three role/password pairs (`sunil`/`litellm`/`n8n`) — a LiteLLM or n8n compromise reads its own DB, not `audit_events` |

Inside TB-nothing: LLM text. Free-form model output can only become action through the plan
validator (§25) and then the C1 chokepoint — there is no path from generated text to a privileged
call that skips `decide()` (§33.3, §33.5).

## 5. Config inventory (complete — every variable and port the system needs)

**App — `apps/api` `Settings` (env / `.env` at repo root).** Validators named per ADR-017/033;
"secret" = `SecretStr` + redaction registry.

| Variable | Default | Secret | Read by / validator |
|---|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://sunil:CHANGE_ME@localhost:5433/sunil` | yes (embedded pwd) | `db/session` (host port 5433 — ADR-032 Amendment 1) |
| `SESSION_SECRET` | — required | yes | session middleware (ADR-007) |
| `SESSION_COOKIE_NAME` | `sunil_session` | no | session middleware; C4/C5 securitySchemes |
| `WEB_ORIGIN` | `http://localhost:3001` | no | CORS + Origin check (ADR-008; `localhost`, never `127.0.0.1`; port 3001 — ADR-032 Amendment 1) |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | no | uvicorn bind |
| `LOG_LEVEL` | `INFO` | no | logging |
| `SUNIL_CONFIG_DIR` | `./config` | no | registry loaders (ADR-016) |
| `SUNIL_TURN_DEADLINE_S` | `40` | no | orchestrator turn budget |
| `SUNIL_LLM_PROVIDER_LANE` | `gateway` | no | provider wiring ONLY — invisible to router policy (ADR-033) |
| `SUNIL_LLM_GATEWAY_BASE_URL` | `http://localhost:4000` | no | `providers/gateway`; ADR-033 validator (loopback ∨ `litellm`) |
| `LITELLM_VIRTUAL_KEY_DEFAULT` | — required in gateway lane | yes | `providers/gateway` auth |
| `LITELLM_VIRTUAL_KEY_<AGENT_ID>` | optional per agent | yes | per-agent key/budget selection (C2 §3) |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | unset in gateway lane | yes | direct lane only (kill-switch fallback) |
| `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL` | canonical values | no | direct lane; ADR-017 validator (canonical ∨ loopback) |
| `GITHUB_TOKEN` | — required for github servers | yes | injected into `github_mcp` child env at spawn (C1 §5), and the native tool |
| `SUNIL_N8N_MCP_BASE_URL` | `http://localhost:5680/mcp` | no | `tools/mcp/http`; ADR-033 validator (loopback ∨ `n8n`); port 5680 — ADR-032 Amendment 1 |
| `SUNIL_N8N_MCP_AUTH_TOKEN` | — required when n8n_mcp configured | yes | auth header for TB5 |
| `SUNIL_APPROVAL_TTL_HOURS` | `72` | no | approvals service (`expires_at`) |
| `SUNIL_APPROVAL_CONSUME_GRACE_HOURS` | `1` | no | approvals service — consume-CAS time bound + stale-approved sweep (C4 §1; Security review 2026-09-10 item 1) |
| `SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL` | unset (webhook off) | no | `core/approvals/notify`; ADR-033 validator |
| `SUNIL_SERVICE_TOKEN` | unset (machine lane off) | yes | `require_service_token` on the chat route only (ADR-035) |
| `SUNIL_MEMORY_PROVIDER` | `fake` until Stream C lands, then `mem0` | no | memory service wiring |

Rulings on this inventory (2026-09-10 security-delta residuals S-1/S-3/S-4): **driver token** —
`+psycopg` (psycopg v3) is normative because it is ADR-002's recorded driver and one dependency
serves both SQLAlchemy 2's async engine and Alembic's sync migration path (`+asyncpg` would add a
second driver against a closed decision). **`SUNIL_TURN_DEADLINE_S=40`** is normative — M1's
live-verified turn ran ~6 s against a 30 s p95 target, and a fail-closed deadline must be tight
enough that a hang surfaces in dev (raise it per-machine in `.env` for step-debugging, never in
this inventory; per-operation tool budgets are C1 `timeout_s`, and a parked turn's human wait is
outside the deadline — §6). **Dev defaults** (documented, no behaviour change): `scripts/dev-up.*`
generates `SUNIL_SERVICE_TOKEN` on `.env` auto-create, so the TB7 machine lane is ON in a
generated dev environment — the table's `unset (machine lane off)` stays the fail-closed
application default when the variable is absent; `SUNIL_MEMORY_PROVIDER` runs `fake` until
Stream C lands (the table default), `mem0` being the committed end-state value in `.env.example`.

**Web — `apps/web`:** `NEXT_PUBLIC_API_BASE_URL` = `http://localhost:8000` (MUST be `localhost`
so the session cookie is same-site with the page origin — the ADR-008 rule; the API may bind
`127.0.0.1`, but the browser-facing name is `localhost`). Next.js dev server runs on **3001**
(ADR-032 Amendment 1 — 3000 is occupied on the build machine).

**Compose services (`infra/docker-compose.yml`, ADR-032 + Amendment 1; every publish MUST bind
`127.0.0.1` — CI-asserted):**

| Service | Image (pinned — platform task actuals) | Ports (host→container) | Container env (secrets stay here) |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:0.8.6-pg17` | `127.0.0.1:5433→5432` | `POSTGRES_USER=sunil`, `POSTGRES_PASSWORD` (secret), `POSTGRES_DB=sunil`; init script creates `litellm` + `n8n` DBs/roles (TB9) |
| `litellm` | `ghcr.io/berriai/litellm:v1.83.14-stable.patch.3` | `127.0.0.1:4000→4000` | `LITELLM_MASTER_KEY` (secret), `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `DATABASE_URL` → `postgres:5432/litellm`; `config.yaml` mounted (`num_retries: 0`, `drop_params: false` — C2 §3 rule) |
| `n8n` | `n8nio/n8n:2.38.5` | `127.0.0.1:5680→5678` | `N8N_ENCRYPTION_KEY` (secret — the vault key), `DB_TYPE=postgresdb`, `DB_POSTGRESDB_HOST=postgres`, `DB_POSTGRESDB_DATABASE=n8n` + role creds; holds tool creds + `SUNIL_SERVICE_TOKEN` in its vault |
| `openhands` (V2-D/F) | pinned at adoption (not yet in compose) | `127.0.0.1:3400→3000` | sandbox config; git creds scoped per ADR-030 item 4 |
| `langfuse` (optional) | pinned at adoption (not yet in compose) | `127.0.0.1:3200→3000` | own secret set; adds ClickHouse if adopted |
| `api` / `web` (later — the api container is a commented stub today; profiles arrive with it, ADR-032 Amendment 1) | built from repo | `8000`/`3001` as above | same app env, with in-network URLs (`http://litellm:4000`, `postgres:5432`, `http://n8n:5678/mcp`) — legal under ADR-033's named-host rule |

Nothing else reads the process environment (M1 law: `settings.py` is the single env seam).

## 6. L-001 trace — one mutating request, end to end, at real addresses

Scenario (ADR-032 host-mode dev topology, Amendment 1 ports): the owner types **"close issue #42 in
codely-isuru/SUNIL"**. `github_mcp.issues_close` is granted `ask_user` for `project_manager` in
`config/permissions.yaml`. Every hop names its mechanism; every mechanism appears in §4/§5.

**Leg 1 — turn request (TB1).** Browser at `http://localhost:3001` sends
`POST http://localhost:8000/api/v1/chat` — `Origin: http://localhost:3001`,
`Cookie: sunil_session=<signed>`, `X-SUNIL-Client: web`, `Accept: application/x-ndjson`,
body `{"message":"close issue #42 in codely-isuru/SUNIL"}`. CORS middleware matches `WEB_ORIGIN`;
`require_client_header` and `require_owner_session` pass (`SESSION_SECRET` verifies the cookie);
Pydantic accepts (1..8000). uvicorn is bound `127.0.0.1:8000`; the browser's `localhost` resolves
there and the cookie is same-site with the page (both `localhost`).

**Leg 2 — plan (TB2, TB3).** `run_turn` loads context (short-term from `messages`; C3 `recall` —
`FakeMemoryProvider` until Stream C, ≤ 800 ms or degrade). Router resolves
`(general_reasoning, internal)` → cloud model via the **gateway lane**:
`POST http://localhost:4000/v1/chat/completions` with `Authorization: Bearer
<LITELLM_VIRTUAL_KEY_PROJECT_MANAGER>`, `response_format=json_schema` (§25 — the plan is
structured output or it is rejected). `SUNIL_LLM_GATEWAY_BASE_URL` passed ADR-033 validation at
boot. LiteLLM (holding the only `ANTHROPIC_API_KEY`) calls `https://api.anthropic.com`, meters the
virtual key, returns. Plan validator: parse → Pydantic → registry re-check (agent exists, tool
`github_mcp`, operation `issues_close` exist in `config/tools.yaml`) → `ValidatedPlan`. Stage
frames (`plan_created`, …) stream back on the open NDJSON response.

**Leg 3 — park (TB9).** Executor reaches the tool step. `ToolManager.execute(project_manager,
github_mcp, issues_close, {owner:"codely-isuru", repo:"SUNIL", issue_number:42})`: params validate
(`extra="forbid"`); `decide()` → `ASK_USER` (`source=config:project_manager.github_mcp.
issues_close`); no approval supplied → **park via the approvals seam**: one transaction on
`postgres@localhost:5433/sunil` inserts the approval (`status='pending'` explicit, `args_hash=
sha256(canonical json)`, `expires_at=now+72h`) + continuation state (plan, cursor=this step) +
`tool_calls` audit row (`permission_decision=ask_user`) + `audit_events` `approval_requested`.
Webhook (TB8): `SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL` unset in this trace — dashboard polling is the
notify path; nothing blocks. The turn finalises: task `parked`; the NDJSON stream ends with its
single `done` frame — envelope `outcome="parked"`, `approval={approval_id:"apr-01J…",
expires_at:…, summary:"github_mcp.issues_close on codely-isuru/SUNIL #42"}`.

**Leg 4 — notify/decide (TB1 again).** The dashboard (same origin `localhost:3001`) polls
`GET http://localhost:8000/api/v1/approvals?status=pending` every 10 s (cookie + header, as Leg 1)
and renders the queue from `params_redacted` + `summary`. The owner clicks Approve →
`POST http://localhost:8000/api/v1/approvals/apr-01J…/decision` body `{"decision":"approve"}`.
The CAS `UPDATE … WHERE status='pending' AND expires_at > now()` wins → `approved`,
`decided_at/decided_by` set; audit `approval_approved`; 200 returns the row. A second click would
get `409 {current_status:"approved"}`.

**Leg 5 — resume (TB4, TB6).** The decision handler schedules `run_continuation(state)` (ADR-031
in-process task). It re-enters `ToolManager.execute(…, approval="apr-01J…")` (ADR-031 Amendment 1
— the manager, not the executor, owns consume): `decide()` still says `ASK_USER` (policy unchanged
— the approval, not a policy override, is what satisfies it); the manager recomputes the binding
from re-validated params and calls `ApprovalsService.consume` — binding matches, within
`SUNIL_APPROVAL_CONSUME_GRACE_HOURS` of `decided_at`, CAS `approved→consumed`, the attempt audit
row committing in the same transaction (C1 §2.1 step 4). The
`MCPToolAdapter(kind=mcp_stdio)` for `github_mcp` — spawned at app start with child env containing
ONLY `GITHUB_TOKEN` (C1 §5) — sends `tools/call issues_close {…}` over stdio (JSON-RPC,
`timeout_s=30` from `config/tools.yaml`); the server calls `https://api.github.com` with the PAT it
alone holds. Result returns, is size-capped and wrapped as untrusted data (C1 §3); `tool_calls`
audit row written (`adapter_kind=mcp_stdio`, `server_id=github_mcp`, `approval_id`, `outcome=ok`).

**Leg 6 — finalise.** The continuation runs the plan's remaining analysis step through TB2/TB3
(gateway again, streaming irrelevant — no client attached), appends the assistant message to the
original conversation (`resumed_from_approval_id=apr-01J…`), marks the task `completed`. The
owner's next dashboard poll shows the approval `consumed` and the conversation shows the outcome.
Audit chain for the whole episode, in order: `request_received … plan_created`,
`tool_call(ask_user)`, `approval_requested`, `approval_approved`, `tool_call(ok, approval_id)`,
`memory_written` (if rules fire), `final_response` — ROADMAP §28's spine, queryable by
`request_id`.

**Inventory check (the L-001 discharge):** mechanisms this trace consumed — `WEB_ORIGIN`,
`SESSION_SECRET`/`SESSION_COOKIE_NAME`, `X-SUNIL-Client`, ports 3001/8000/4000/5433 (ADR-032
Amendment 1), `SUNIL_LLM_GATEWAY_BASE_URL` + ADR-033 validator,
`LITELLM_VIRTUAL_KEY_PROJECT_MANAGER` (falls back to `_DEFAULT`), litellm-held
`ANTHROPIC_API_KEY`, `DATABASE_URL`, `SUNIL_APPROVAL_TTL_HOURS`,
`SUNIL_APPROVAL_CONSUME_GRACE_HOURS` (leg 5's consume bound), `GITHUB_TOKEN` + `credential_env`
spawn rule, `config/{models,tools,permissions}.yaml` via `SUNIL_CONFIG_DIR`,
`SUNIL_TURN_DEADLINE_S` (legs 2–3 only — the deadline governs the turn, not the human wait, which
is exactly why ADR-031 parks). Every item appears in §5. Two mechanisms the
trace deliberately did NOT need: `SUNIL_SERVICE_TOKEN` (browser lane) and the webhook URL (unset) —
both exist in §5 for the paths that do need them (TB7/TB8).

## 7. Failure posture (summary; drills are Phase 3)

LiteLLM down → `ProviderError(kind="timeout"/"overloaded")`, turn fails visibly; recovery = lane
flip to `direct` (ADR-033, transport-only). n8n down → its MCP tools return `transport_error`,
triggers stop firing (no queued backlog — triggers are stateless calls); native/stdio tools
unaffected. Postgres down → the app is down, honestly (it is the audit spine; running unaudited is
not a degraded mode, per §33.10-11). Memory down → degraded recall, writes fail loudly (C3 §2).
Approvals sweeper missed → lazy expiry at read/decide covers it (C4 §1).

## 8. What Phase 0 exits with

The five contract files + this document + ADR-031..035 (with their fix-round amendments) merged;
fakes and contract suites implemented under `apps/api/tests/{fakes,contracts}/` (QA, from the
specs in each contract's § "FAKE specification"); `infra/docker-compose.yml` + `.env.example`
**kept in parity with §5** — §5 now matches platform reality (ADR-032 Amendment 1), and the CI
parity check the amendment requires is what keeps regeneration from ever silently reverting real
ports again; Compose boot green. Then the six streams start against frozen paper, not against each
other's code.
