# SUNIL M1 — Ordered Build Plan (T1 … T20)

**Author:** Solution Architect, Minions Team 18 · **Status:** for Gate 2 · **Date:** 2026-08-14
**Milestone:** M1, the `ROADMAP.md` §22 vertical slice. **Due 2026-08-17.**
**Builds from:** [`ARCHITECTURE_V1.md`](ARCHITECTURE_V1.md) · [`decisions/`](decisions/) ADR-000…013 ·
[`THREAT_MODEL.md`](THREAT_MODEL.md) · [`REQUIREMENTS_V1.md`](REQUIREMENTS_V1.md) ·
[`design/M1_CHAT_SPEC.md`](design/M1_CHAT_SPEC.md) · [`design/DESIGN_SYSTEM.md`](design/DESIGN_SYSTEM.md)

---

## 0. How to use this

Twenty tasks, six lanes, **strict file ownership so parallel lanes never collide.** A task's
"Owns" list is exclusive: no other task edits those paths. The three places where one task must
touch another's file are called out explicitly and are always within a single lane, so they are
sequential, not concurrent.

Lanes: **BE-1** backend core · **BE-2** backend integrations · **FE** frontend · **QA** ·
**SEC** security · **OPS** devops.

**⚠ Date ambiguity to resolve before Day 1.** `REQUIREMENTS_V1.md`'s header reads "specified for
**build-start** on 2026-08-17" while its §2 table, `STATUS.md` and ADR-000 all read 2026-08-17 as the
**due date**; `M1_CHAT_SPEC.md` inherited the build-start reading. This plan assumes **due
2026-08-17, build starts the day Gate 2 closes.** The Delivery Manager should confirm with the owner,
because the two readings differ by the entire milestone.

### Rules for everyone building this

1. **Escalate, do not invent.** If this plan or the architecture does not answer a question, ask the
   Architect through the Delivery Manager. You will get an exact config name and a default, not a
   direction. Inventing a mechanism that contradicts a document is how M1 slips.
2. **The contract in §6 is frozen.** Changing an endpoint, a field name or a failure kind requires an
   Architect ruling, because the frontend and QA are building against it *before* the backend exists.
3. **Do not name a library that is not in `ARCHITECTURE_V1.md` §14.3.** Every entry there was checked
   to exist for Python 3.13 / Node 24 on 2026-08-14. Adding one is an escalation.
4. **`python`, never `python3`** on this machine (`ENVIRONMENT.md` §1 — the Store stub).
5. **Never bind port 4317.** It is the Minions Portal.
6. **Scoped `git add <path>` only, never `git add -A`.** Several agents commit to `main` concurrently.
7. **Definition of done, every task:** code + its own unit tests green + `ruff` clean + the named
   requirements demonstrably satisfied + committed and pushed.

---

## 1. Dependency graph

```
 T1 foundation ─┬─ T2 data layer ─┬─ T4 trace spine ── T5 API skeleton ──┐
                │                 │                                      │
                └─ T3 registries ─┼─ T6 router ──┬─ T9 plan validation ──┤
                                  ├─ T7 permissions ─┐                   │
                                  │                  ├─ T8 tools ────────┤
                                  │                  │                   │
                                  │                  └── T10 agents ─────┤
                                  │                                      │
                                  └──────────────────────────────────────┴─▶ T11 orchestrator turn
                                                                              │
                                                             T12 SSE ◀────────┤ (descope lever)
                                                             T13 trace API ◀──┘
 T14 web scaffold ── T15 chat components ── T16 API client + useTurn ──┐
 T17 dev topology (OPS, independent)                                   ├─▶ T20 integration + runbook
 T18 QA red exit tests (starts hour 0, against §6 contract)            │
 T19 security review + import boundaries ──────────────────────────────┘
```

**Critical path:** T1 → T2 → T4 → T5 → T11 → T20. Everything else is parallel or slack.

---

## 2. Backend core lane (BE-1)

### T1 — Backend foundation and tooling
**Deps:** none. **Blocks:** everything backend.
**Owns:** `apps/api/pyproject.toml`, `apps/api/sunil/__init__.py`, `apps/api/sunil/settings.py`,
`apps/api/sunil/logging.py`, `apps/api/sunil/main.py` *(created here; extended by T5 — same lane)*,
`.env.example`, `scripts/dev-api.ps1`, `apps/api/README.md`, one appended line in `.gitignore` (`var/`).
**Build:** venv + `pip install -e ".[dev]"`; `pydantic-settings` `Settings` with every variable in
`ARCHITECTURE_V1.md` §14.4, secrets as `SecretStr`; `structlog` JSON renderer with `contextvars`,
uvicorn's loggers routed into the same chain; `create_app()` returning a bare `FastAPI`; ruff +
pytest config in `pyproject.toml`.
**Satisfies:** FR-005, FR-008. **Exit tests enabled:** none directly (unblocks all).
**Watch:** `.env.example` carries **placeholders only** — a real value here is an ET-10 failure.

### T2 — Data layer, models, migration `0001`
**Deps:** T1.
**Owns:** `apps/api/alembic.ini`, `apps/api/migrations/**`, `apps/api/sunil/db/base.py`,
`apps/api/sunil/db/models.py`, `apps/api/sunil/db/session.py`, `scripts/seed-owner.py`.
**Build:** all eleven tables from `ARCHITECTURE_V1.md` §7.3 — `users, conversations, messages,
workflows, tasks, task_status_events, plans, tool_calls, approvals, memories, llm_calls,
audit_events`. **Obey §7.2's portability rules exactly** (text UUIDs, `sa.JSON().with_variant(JSONB,
"postgresql")`, UTC datetimes, `BigInteger` micro-USD for money, no native enums, no server defaults).
Async engine + `async_sessionmaker`; async `env.py`; `downgrade()` implemented; startup asserts
`alembic_version == head`.
**Satisfies:** FR-002, FR-021, FR-063, FR-103, FR-144. **Exit tests:** ET-2, ET-4, ET-9 (storage side).
**Watch:** `Numeric` on SQLite is lossy and warns — use micro-USD integers. Autogenerate is a draft,
not a commit (ADR-002).

### T4 — Observability spine: trace, audit, redaction
**Deps:** T1, T2. **Blocks:** T5, T6, T8, T11.
**Owns:** `apps/api/sunil/core/trace/{stages.py,context.py,emitter.py}`,
`apps/api/sunil/core/audit/writer.py`, `apps/api/sunil/redaction.py`.
**Touches (one line, same lane):** `sunil/logging.py` — register the redaction processor.
**Build:** `TraceStage` StrEnum with exactly the twelve NFR-020 names; `TraceContext` holding
`request_id`, `user_id`, `conversation_id`, `started_at`, `seq`; **one** `emit()` writing to three
sinks (log line, `audit_events` row, trace bus — the bus is a no-op stub until T12).
`redaction.register()` + `redaction.scrub()` per ADR-006, wired as a structlog processor **and**
called before every `llm_calls` / `tool_calls` / `audit_events` insert.
**Satisfies:** FR-008, FR-067, NFR-001/005/006/020. **Exit tests:** **ET-6, ET-10**.
**Watch:** untrusted content goes in a *field*, never interpolated into a log message string (T-32).

### T5 — API skeleton: middleware, auth, health
**Deps:** T1, T2, T4.
**Owns:** `apps/api/sunil/api/{deps.py,schemas.py,middleware.py}`,
`apps/api/sunil/api/routes/{auth.py,health.py}`.
**Extends (same lane):** `sunil/main.py` — the middleware list and router registration.
**Build:** middleware via the **explicit constructor list**, CORS outermost
(`ARCHITECTURE_V1.md` §3.3); `RequestContextMiddleware` accepting/validating `X-Request-Id` as UUID4
and binding it to contextvars; `SessionMiddleware`; `require_owner_session` (401) and
`require_client_header` (403, checks `X-SUNIL-Client` and `Origin`); login with `hashlib.scrypt` and
a 5-failure/60 s throttle; `GET /api/v1/health` returning liveness + alembic revision.
**Satisfies:** FR-001, FR-004, FR-007, FR-026. **Exit tests:** prerequisite for all.
**Watch:** `allow_origins` must be the explicit `WEB_ORIGIN`, never `"*"` — a wildcard with
`allow_credentials=True` is rejected by every browser (T-07).

### T9 — Plan schema, models, validator, `ValidatedPlan`
**Deps:** T3, T6. **This is the highest-value task in M1.**
**Owns:** `apps/api/sunil/core/orchestrator/{plan_schema.py,plan_models.py,plan_validator.py}`.
**Build:** all five layers of ADR-004 exactly — runtime schema built from the registries with `enum`
whitelists and the `__unknown__` / `none` sentinels; `PlanDraft` with `extra="forbid"` and the
`0.0 ≤ confidence ≤ 1.0` check; `validate_plan()` re-checking against live registries **and**
`permissions.yaml`; `ValidatedPlan` constructible only with the module-private token.
**Satisfies:** FR-060, FR-061, FR-062, NFR-040/041. **Exit tests:** **ET-7**, and ET-11's mechanism.
**Watch:** the schema must stay inside the verified `output_config` feature envelope
(`ARCHITECTURE_V1.md` §4.3) — **no `minimum`/`maximum`, no `minLength`, no nullable union types.**
Ship all six tests from §6.3; deleting one deletes the control.

### T11 — Orchestrator turn, conversation gateway, chat endpoint
**Deps:** T2, T4, T5, T9, T10. **The integration task.**
**Owns:** `apps/api/sunil/core/orchestrator/turn.py`, `apps/api/sunil/core/conversations/**`,
`apps/api/sunil/core/tasks/**`, `apps/api/sunil/core/workflows/**`,
`apps/api/sunil/core/memory/short_term.py`, `apps/api/sunil/api/routes/chat.py` *(new file in T5's
directory)*.
**Build:** the twelve-stage pipeline from `ARCHITECTURE_V1.md` §3.4; create/load conversation and
persist both messages; Task + Workflow + `task_status_events`; bounded plan retry with prior errors
fed back; agent invocation; final-response LLM call; the four failure outcomes of §11.3 returned as
HTTP 200 with a discriminated `failure.kind`; `unknown_project` returning `known_projects` from the
registry.
**Satisfies:** FR-020/021/022, FR-063–067, FR-140, NFR-060/071. **Exit tests:** ET-1, ET-2, ET-3,
ET-5, ET-6, ET-8, ET-11.
**Watch:** a failed turn must still emit stage 12 (ET-8). The final chat message is the LLM's prose,
never raw tool JSON (ET-5).

### T12 — SSE progress channel · **DESIGNATED DESCOPE LEVER**
**Deps:** T4, T11.
**Owns:** `apps/api/sunil/core/trace/bus.py`, `apps/api/sunil/api/routes/events.py`.
**Touches (one line, same lane):** `core/trace/emitter.py` — publish to the bus.
**Build:** `TraceBus` per ADR-009 — owning `user_id`, 64-event replay buffer, subscriber queues,
5-minute TTL, first-claim-wins ownership with 403 on mismatch; `StreamingResponse` with
`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`; `event: stage` frames, a
terminal `event: done`, a `: ping` heartbeat every 15 s, close on terminal or 120 s. Gated by
`SUNIL_PROGRESS_EVENTS`.
**Satisfies:** the Designer's M1_CHAT_SPEC §5.3. **Exit tests:** none — it is cosmetic by construction.
**If the date is at risk, this task is dropped**, `SUNIL_PROGRESS_EVENTS=false`, and T16's fallback
stepper carries the UI. Decide by the end of Day 2, not on Day 3.

---

## 3. Backend integrations lane (BE-2)

### T3 — Configuration registries
**Deps:** T1.
**Owns:** `config/agents.yaml`, `config/permissions.yaml`, `config/projects.yaml`,
`config/models.yaml`, `config/tools.yaml`, `apps/api/sunil/core/registry/**`.
**Build:** the exact file contents in `ARCHITECTURE_V1.md` §9.2, §10.2 and §4.4 (including the pinned
price table and `pricing_version`); typed loaders; **startup cross-validation** — every agent in
`permissions.yaml` exists in `agents.yaml`, every tool/operation referenced exists in `tools.yaml` —
refusing to boot on mismatch.
**Satisfies:** FR-080, FR-084, FR-100, FR-107. **Exit tests:** ET-11 (the project registry half).
**Watch:** the target repository is `codely-isuru/easy_clean_workforce` and it lives **only** in
`config/projects.yaml` (ADR-000 Q7). Hard-coding it anywhere is a review failure.

### T6 — Provider interface and Model Router
**Deps:** T3, T4.
**Owns:** `apps/api/sunil/providers/{base.py,anthropic.py,registry.py}`,
`apps/api/sunil/core/routing/{router.py,capabilities.py,pricing.py,retry.py}`.
**Build:** the protocol and dataclasses of `ARCHITECTURE_V1.md` §4.2; the Anthropic adapter against
the verified surface in §4.3 — `AsyncAnthropic`, `max_retries=0`, `output_config={"format":
{"type":"json_schema","schema":…}}`, `usage.input_tokens`/`output_tokens`, `_request_id`, and the
exception mapping to `ProviderTransientError`/`ProviderPermanentError`; router capability lookup,
3-attempt backoff with jitter, one `llm_calls` row **per attempt**, cost in micro-USD from the pinned
table.
**Satisfies:** FR-040/041/042/045/046, NFR-010/030/070. **Exit tests:** ET-8, **ET-9**.
**Watch:** `sunil/providers/` is the **only** package permitted to `import anthropic` (FR-040's own
acceptance criterion). T19 tests this.

### T7 — Permission engine
**Deps:** T3.
**Owns:** `apps/api/sunil/core/permissions/engine.py`.
**Build:** the `decide()` function of `ARCHITECTURE_V1.md` §9.2 — three-valued `Decision`, structural
default-deny (the missing-key branch returns DENY), a `PermissionResult` carrying `reason` and
`source`.
**Satisfies:** FR-120, FR-121, NFR-007. **Exit tests:** **ET-4**.
**Watch:** ship `test_empty_permission_config_denies_everything` — it is what makes "default-deny"
a fact rather than a description.

### T8 — Tool framework and the GitHub adapter
**Deps:** T2, T3, T4, T7.
**Owns:** `apps/api/sunil/core/tool_framework/{base.py,manager.py}`,
`apps/api/sunil/tools/github/{adapter.py,projection.py}`.
**Build:** `ToolManager.execute()` in the exact eight-step order of `ARCHITECTURE_V1.md` §9.3;
Pydantic `params_model` per operation; `tool_calls` row written before the adapter is reached; every
adapter exception normalised, never propagated. GitHub: three concurrent `httpx` GETs (commits, open
PRs, open issues), `Authorization: Bearer`, `Accept: application/vnd.github+json`,
`X-GitHub-Api-Version: 2022-11-28`, 15 s timeout; **`owner`/`repo` resolved from `config/projects.yaml`,
never from the plan**; the allow-listed, length-capped projection of §9.4 control 3 with issue and PR
**bodies excluded**.
**Satisfies:** FR-101–105, NFR-002/008/011/012. **Exit tests:** **ET-4**, and ET-1's data half.
**Watch:** GitHub's `/issues` endpoint **also returns pull requests** — filter items carrying a
`pull_request` key or every PR is counted twice.

### T10 — Agent framework and the Project Manager agent
**Deps:** T3, T6, T8, T9.
**Owns:** `apps/api/sunil/core/agent_framework/{base.py,runner.py}`,
`apps/api/sunil/agents/project_manager/agent.py`.
**Build:** `AgentContext` exposing exactly `call_tool`, `ask_model`, `memory`, `trace` — **no DB
session, no HTTP client, no secrets** (NFR-007); the runner rejecting a tool absent from the agent's
own config *before* the Tool Manager (FR-082). The PM agent does ADR-000 Q2 and nothing more: resolve
project → one read-only call → LLM summary in 2–4 sentences → return. The analysis call passes **no
`tools` parameter** and wraps the projection in `<untrusted_tool_result>` with the delimiter escaped
(THREAT_MODEL §5.1 control 1 and 4).
**Satisfies:** FR-080/081/082/084, NFR-007/011/012. **Exit tests:** ET-3, **ET-5**.
**Watch:** the summary must reference only data present in the tool result. "Never claim anything the
tool result does not show" is in the agent's instructions for a reason (ET-1).

### T13 — Trace read endpoint
**Deps:** T4, T11.
**Owns:** `apps/api/sunil/api/routes/trace.py`.
**Build:** `GET /api/v1/trace/{request_id}` reassembling `audit_events` + `llm_calls` + `tool_calls`
summaries. This is the NFR-050 verification query and the seed of M8's NFR-021 view.
**Satisfies:** NFR-050. **Exit tests:** assists ET-6, ET-9.

---

## 4. Frontend lane (FE)

### T14 — Web scaffold and the token contract
**Deps:** none — **starts at hour 0.**
**Owns:** `apps/web/{package.json,pnpm-lock.yaml,next.config.ts,tsconfig.json,tailwind.config.ts,postcss.config.js}`,
`apps/web/src/app/{layout.tsx,globals.css}`, `apps/web/src/styles/**`.
**Build:** `pnpm create next-app` **without Tailwind**, then `pnpm add -D tailwindcss@3.4.19 postcss
autoprefixer` (ADR-012 — the scaffold now defaults to v4 and the design system is v3 syntax). Paste
`DESIGN_SYSTEM.md` §1's `theme.extend` block **verbatim**; wire the three font stacks; implement the
§7 accessibility floor (focus ring, reduced motion, rem sizing).
**Watch:** `apps/web` gets its **own** lockfile. Do not `npm install` at the repo root — a stale
1.1 GB `node_modules/` from the retired build is still there (`ENVIRONMENT.md` §2).

### T15 — Chat components
**Deps:** T14.
**Owns:** `apps/web/src/components/chat/**` — one file per `M1_CHAT_SPEC.md` §7 component:
`ChatShell, TopBar, MessageList, MessageBubble, AssistantMessage, TraceDisclosure, WorkIndicator,
ErrorCard, Composer, SuggestionChips, JumpToBottomPill, StatusDot`.
**Build:** presentational only, driven by props — no data fetching. All four `ErrorCard` variants with
the Designer's **final copy, verbatim, not paraphrased** (§5.6–5.9). Components stay chrome-agnostic
(`DASHBOARD_DIRECTION.md` §2).
**Satisfies:** FR-003.
**Watch:** the markdown renderer must **not** enable raw HTML (THREAT_MODEL T-02). Desktop-only
Enter-to-send (§1.2). Reduced-motion handling on `WorkIndicator`.

### T16 — API client, auth screen, `useTurn`
**Deps:** T14, T15. **Contract only** — builds against §6 below with a local stub, not against a
running backend. Integration is T20.
**Owns:** `apps/web/src/lib/{api.ts,phases.ts,copy.ts,useTurn.ts}`,
`apps/web/src/app/(chat)/page.tsx`, `apps/web/src/app/login/page.tsx`.
**Build:** `fetch` with `credentials:"include"`, `X-SUNIL-Client: web`, client-generated
`X-Request-Id`; `EventSource` with `withCredentials`; the 12→4 phase map and all human labels
(**the API sends enums only**); 400 ms minimum phase display, 20 s reassurance line, 45 s client
timeout; `AbortController` cancel with the Designer's §6 copy **unchanged, including the "even if I
finish it in the background" clause** (ADR-010); and the **fallback stepper** for when
`SUNIL_PROGRESS_EVENTS` is off or `EventSource` errors (ADR-009).
**Satisfies:** FR-003, FR-007 (client side). **Exit tests:** ET-1's UI half, ET-11's UI half.
**Watch:** `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` — **`localhost`, never `127.0.0.1`**, or
the session cookie is silently withheld (ADR-008).

---

## 5. OPS, QA and Security lanes

### T17 — Local dev topology (OPS)
**Deps:** T1, T2. **Independent of the backend's progress.**
**Owns:** `infra/docker/{docker-compose.yml,Dockerfile.api}`, `scripts/{dev-check.ps1,dev-web.ps1}`,
`docs/RUNBOOK.md`.
**Build:** compose per `ARCHITECTURE_V1.md` §14.2 — `pgvector/pgvector:pg17`, Redis behind a
non-default `queue` profile, api behind a `full` profile. **`dev-check.ps1` is the valuable part:**
probe `http://localhost:8000/api/v1/health`, assert `WEB_ORIGIN` and `NEXT_PUBLIC_API_BASE_URL` both
use `localhost` and not `127.0.0.1`, assert nothing is bound to 4317 by us, and print the exact
remedy on failure.
**Watch:** compose must not be a prerequisite for anything in M1 (ADR-001/005/013). If Docker is
still down, T17 still completes — the file is authored, not run.

### T18 — QA red exit-test harness
**Deps:** the §6 contract only. **Starts hour 0, red.**
**Owns:** `apps/api/tests/{integration,exit}/**`, `apps/api/tests/conftest.py`, fixtures and the fake
provider.
**Build:** ET-1 … ET-11 as executable tests, red first; a `FakeProvider` implementing `LLMProvider`
for deterministic and fault-injected runs (malformed plan for ET-7; transient-then-success for ET-8);
DB assertions for ET-2/3/4/9; the twelve-stage ordering query for ET-6; the unknown-project path for
ET-11.
**Split of ownership:** backend engineers own `apps/api/tests/unit/**` for their own modules; QA owns
`integration/` and `exit/` exclusively; Security owns `security/`. No file is written by two lanes.

### T19 — Security review, import boundaries, injection tests (SEC)
**Deps:** T8, T11 for the injection test; the boundary tests can be written earlier.
**Owns:** `apps/api/tests/security/**`.
**Build:** **DC-10's import-boundary tests as AST-walking tests, not lint config** (so no lane has to
edit `pyproject.toml`): only `sunil/providers/**` may import `anthropic`; only
`sunil/core/tool_framework/**` may import `sunil.tools.*`; `sunil/core/**` may not import `sunil.api`.
Plus the ET-10 secret-scan tests, the T-15 injection test (a commit message containing an embedded
instruction), the T-16 test that repo coordinates never originate in a plan, and the
projection-excludes-bodies test. Then a design/code review against `THREAT_MODEL.md`.
**Satisfies:** NFR-001/002/005/007/011/012. **Exit tests:** **ET-10**.

### T20 — Integration, latency measurement, runbook
**Deps:** all. **Lane: BE-1 + QA together.**
**Owns:** `README.md` (M1 run instructions), `apps/api/tests/exit/test_latency.py`, and the final
`docs/STATUS.md` update **by the Delivery Manager, not by an engineer**.
**Build:** run the full stack; make ET-1 … ET-11 green; five timed end-to-end runs, report p95 against
NFR-060's 30 s; confirm the frontend renders both the SSE and fallback progress paths.

---

## 6. The frozen contract (build against this, not against each other)

Frontend and QA start before the backend exists. **These names are fixed; changing one is an
Architect escalation.**

```
POST /api/v1/auth/login      {username, password}                    → 200 {user:{id,name}} + Set-Cookie
POST /api/v1/auth/logout                                             → 204
GET  /api/v1/auth/session                                            → 200 {authenticated, user|null}
GET  /api/v1/health                                                  → 200 {status,"revision":"0001"}

POST /api/v1/chat
  headers: X-SUNIL-Client: web · X-Request-Id: <uuid4> · Cookie
  body:    {message: string(1..8000), conversation_id: string|null}
  → 200 {request_id, conversation_id, outcome: "ok"|"failed",
         message: {id, role:"assistant", content, created_at} | null,
         task: {id, status, assigned_agent} | null,
         failure: {kind, known_projects?: [{key, display_name}]} | null,
         trace: [{stage, offset_ms, detail}],
         usage: {input_tokens, output_tokens, cost_usd}}
  → 401 no session · 403 missing X-SUNIL-Client / bad Origin · 422 bad body or bad X-Request-Id

GET  /api/v1/chat/{request_id}/events        (SSE, withCredentials)
  event: stage  data: {stage, offset_ms, detail}
  event: done   data: {outcome}
  : ping                                     (heartbeat, 15 s)

GET  /api/v1/trace/{request_id}              → 200 {stages[], llm_calls[], tool_calls[]}
```

`failure.kind` ∈ `provider_error | tool_failed | plan_rejected | unknown_project` → the Designer's
`ErrorCard` variants `generic | tool_failed | plan_rejected | unknown_project`.

`stage` ∈ the twelve NFR-020 names: `message_received, context_loaded, memory_retrieved,
model_selected, llm_io, plan_created, agent_started, tool_requested, permission_decision, tool_result,
agent_result, final_response`.

**The API sends enums and data. The web app owns every human-readable string** — labels, phase names
and all failure copy (`ARCHITECTURE_V1.md` §11.2).

---

## 7. Exit-test coverage map

| Exit test | Made passable by |
|---|---|
| **ET-1** coherent answer traceable to real data | T8 + T10 + T11 + T16 |
| **ET-2** Task + Workflow + schema-valid plan JSON | T2 + T9 + T11 |
| **ET-3** `assigned_agent` = Project Manager | T10 + T11 |
| **ET-4** exactly one ToolCall, decision `ALLOW` | T7 + T8 |
| **ET-5** tool result feeds the analysis call; prose, not JSON | T6 + T10 |
| **ET-6** all twelve stages, in order, from logs alone | **T4** + T11 |
| **ET-7** malformed plan → zero ToolCalls | **T9** |
| **ET-8** transient failure recovers or fails cleanly | T6 + T11 |
| **ET-9** cost record per LLM call, non-zero tokens | T2 + T6 |
| **ET-10** no secret in any prompt or persisted log | **T4** + T19 |
| **ET-11** unknown project answered, not crashed or faked | T3 + T9 + T11 + T16 |

---

## 8. Schedule, slack and the descope order

Assuming Gate 2 closes on 2026-08-14 and build runs 08-15 → 08-17.

| Day | BE-1 | BE-2 | FE | QA / SEC / OPS |
|---|---|---|---|---|
| **1** | T1 → T2 → T4 | T3 → T7 → T6 | T14 → T15 begins | T18 red suite; T17 |
| **2** | T5 → T9 → T11 begins | T8 → T10 | T15 → T16 | T18 continues; T19 boundary tests |
| **3** | T11 → T12 | T13 | T16 integration | T19 injection tests; **T20** |

**Descope order if 08-17 is at risk** — take them in this order, not by improvisation:

1. **T12** (SSE) → `SUNIL_PROGRESS_EVENTS=false`, T16's fallback stepper carries the UI. Pre-agreed
   in ADR-009; costs nothing but honesty about timing. **Decide by end of Day 2.**
2. **T13** (trace read endpoint) → the trace already ships inside the chat response, so
   `TraceDisclosure` still works; only the debug endpoint is lost.
3. **T17's compose file** → M1 does not use it (ADR-001/005/013); author it after the milestone.
4. **The `approvals` table** → drop from `0001`; M5 adds a migration. Saves ten minutes; listed only
   for completeness.

**Never descoped, in any circumstance:** T4 (the trace spine), T7 (permissions), T9 (plan
validation), T19's ET-10 tests. Those four are what make the M1 claims true, and ET-6, ET-7 and ET-10
are graded on them.

---

## 9. Known traps, collected

Each of these has cost someone a day somewhere. They are here so they cost nobody a day here.

1. `python3` launches the Microsoft Store stub on this machine. Always `python`.
2. Mixing `127.0.0.1` and `localhost` between the two dev servers silently withholds the session
   cookie — different **sites**, so `SameSite=Lax` blocks it on POST. Both must be `localhost`.
3. `allow_origins=["*"]` with `allow_credentials=True` is rejected by every browser. Use `WEB_ORIGIN`.
4. Starlette applies the **most recently added** middleware outermost. Use the explicit constructor
   list and put CORS first, or your 401 arrives without CORS headers and looks like a network error.
5. `create-next-app` now scaffolds Tailwind v4. Scaffold without it and add `3.4.19` explicitly.
6. GitHub's `/issues` endpoint also returns pull requests. Filter on the `pull_request` key.
7. `output_config` JSON Schema does **not** support `minimum`/`maximum`/`minLength` or nullable union
   types. Use `enum` sentinels and validate ranges in Pydantic.
8. `Numeric` on SQLite is lossy and warns. Money is `BigInteger` micro-USD.
9. The `TraceBus` is in-process — `uvicorn --workers 1` or progress events break silently.
10. `pip index versions` cannot parse extras; check `psycopg`, then install `psycopg[binary]`.
