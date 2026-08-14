# SUNIL V1 — Architecture

**Author:** Solution Architect, Minions Team 18 · **Status:** for Gate 2 (human review) · **Date:** 2026-08-14
**Plan of record:** [`docs/ROADMAP.md`](ROADMAP.md) — `§n` references below are to that document.
**Requirements:** [`docs/REQUIREMENTS_V1.md`](REQUIREMENTS_V1.md) — `FR-xxx` / `NFR-xxx` / `ET-n`.
**Settled scope:** [`docs/decisions/ADR-000-gate-1-scope-decisions.md`](decisions/ADR-000-gate-1-scope-decisions.md) — not reopened here.
**Design specs this must serve:** [`docs/design/M1_CHAT_SPEC.md`](design/M1_CHAT_SPEC.md), [`docs/design/DESIGN_SYSTEM.md`](design/DESIGN_SYSTEM.md).
**Decisions:** ADR-001 … ADR-013 in [`docs/decisions/`](decisions/). **Threat model:** [`docs/THREAT_MODEL.md`](THREAT_MODEL.md).
**Build order:** [`docs/M1_BUILD_PLAN.md`](M1_BUILD_PLAN.md).
**Git workflow (Delivery Manager's document, in force):** [`docs/GIT_WORKFLOW.md`](GIT_WORKFLOW.md).

---

## Amendment log

The owner reviewed this architecture on **2026-08-14** and approved the direction *after targeted
corrections* (his review is archived at `docs/reviews/2026-08-14-owner-architecture-review.md`).
No fundamental decision changed. The corrections below are applied in place; each one is listed
here because my standing convention is that a changed decision is a recorded change, never a
silent edit.

| # | Amendment | Origin | Where |
|---|---|---|---|
| A-1 | The framework package renames (`core/models`→`core/routing`, `core/agents`→`core/agent_framework`, `core/tools`→`core/tool_framework`) are **accepted by the owner**, not merely proposed | review §2.2 | §2.1, §2.2, ADR-011 |
| A-2 | "Exactly three LLM calls" replaced by **logical LLM purposes vs provider attempts**; cost, rate limits, latency and the trace are all counted in provider attempts | review §6 | §1.1, §4.5, §5, §8.1, §13 |
| A-3 | The `ValidatedPlan` claim is narrowed. "Unforgeable" and "no expressible code path" are withdrawn — Python annotations and module-private names are not security boundaries — and replaced by a **runtime `isinstance` guard plus trusted execution metadata** threaded to the Tool Manager | review §7 | §6.1, §6.3, §9.3, ADR-004 Amendment 1 |
| A-4 | **M1 has two logical LLM stages, not three.** The Project Manager agent's analysis summary is the user-facing response; the `final_response` trace stage is still emitted, by deterministic code | review §11 | §1.1, §3.4, §5, ADR-015 |
| A-5 | A **server-side turn deadline** (40 s) is introduced, below the frontend's 45 s client timeout, and retries may not start an attempt that cannot finish inside it | derived from A-2 | §5, §11.3, §14.4 |
| A-6 | **Training-data capture policy** added: `NONE / METADATA_ONLY / REDACTED_FULL / FULL_LOCAL_ONLY` plus `sensitivity`, `retention_class`, `training_eligible` on the five capture tables | review §10 | §7.3, §13, ADR-014 |
| A-7 | **Config deployment policy** stated: `config/*.yaml` is mounted, never baked into an image, and a permissions change is change-controlled even though it needs no code deploy | review §12 | §14.5, ADR-016 |
| A-8 | **Minimal CI lands in M1** (backend `ruff` + `pytest`, frontend typecheck + build, security import-boundary and critical security tests) and gates every merge | review §8 | §16 debt D-6, `M1_BUILD_PLAN.md` T21 |
| A-9 | The M1 date is settled: **build starts 2026-08-14, M1 is due 2026-08-18.** No document may state otherwise | review §9 + owner ruling | throughout |
| A-10 | **The owner granted one extra day on 2026-08-14** (08-17 → 08-18) rather than descope, after `M1_BUILD_PLAN.md` §8.4 reported the MUST-HAVE set missing 08-17 in the expected case. Every 08-17 reference in this document, the threat model and ADR-001/009 was re-dated with it | DM, on the owner's decision | throughout |

---

## 0. How to read this

This document describes **V1** and calls out **M1** — the §22 vertical slice due **2026-08-18** — as the
first buildable slice. Anything marked **M1** is being built now. Anything marked **V1 (later)** is
designed for but not built this week; where a later capability constrains an M1 decision, the seam
is named so the later work is additive rather than a rewrite.

Three rules govern every decision below:

1. **Deterministic code holds the privilege.** LLMs produce *proposals*; only validated, typed
   objects reach an executor, and only the permission engine decides whether a tool runs
   (§33 rules 2, 3, 5).
2. **Buildable by a Sonnet engineer inside the window that closes on 2026-08-18** (build started
   2026-08-14). Where depth costs the M1 date, depth is deferred and the debt is recorded in §16.
   Elegance that misses 2026-08-18 is the wrong call.
3. **Nothing is claimed that the code will not have.** Deferred controls live in the threat model
   with an owning milestone, never in prose that implies they exist.

---

## 1. Component decomposition and the deterministic / LLM boundary

### 1.1 The line

`ROADMAP.md` §2 and §33.2 are explicit: the Central Orchestrator is software, not a model. This
architecture draws the line as a **hard interface**, not a convention.

| Concern | Owner | Why |
|---|---|---|
| Receiving a request, assigning a request ID, authenticating | Deterministic (`api/`) | Security boundary |
| Loading conversation + memory context | Deterministic (`core/conversations`, `core/memory`) | Retrieval policy is code |
| **Interpreting the request into a plan** | **LLM** (via Model Router) | Natural-language understanding |
| Validating the plan | Deterministic (`core/orchestrator/plan_validator.py`) | §33.3 — this is the privileged gate |
| Deciding which agent runs, in which order | Deterministic (`core/orchestrator/turn.py`) | Follows the *validated* plan; no re-planning in M1 |
| Deciding whether a tool may run | Deterministic (`core/permissions`) | §11, §33.5 — never model judgement |
| Validating tool arguments | Deterministic (Pydantic models on each operation) | §26.8 |
| Executing the tool call | Deterministic (`core/tool_framework` → `tools/*`) | §10 |
| **Analysing the tool result, and writing the answer in the same call** | **LLM** | Reasoning over data + response generation. In M1 these are one purpose, not two (ADR-015) |
| Composing the turn's user-facing message | Deterministic in M1 (`core/orchestrator` persists the agent's summary); an LLM synthesiser from M6, when several agent results must be merged | ADR-015 |
| Recording every stage, cost, and decision | Deterministic (`core/trace`, `core/audit`) | §28, §33.10 |

**Logical LLM purposes are not provider API calls. Do not conflate them.**

An M1 turn contains **two logical LLM purposes** — *planning* and *analysis*. (The V1 design has a
third, *final-response synthesis*; ADR-015 removes it from M1 because there is one agent and one
result to report, so the analysis call already produces the user-facing prose. The `final_response`
trace stage is still emitted — by deterministic code — so the trace shape and the frontend are
unchanged.)

Each **logical** request may produce **multiple provider attempts**:

```
logical planning request
├── provider attempt 1        transport failure  → llm_calls row, attempt=1
├── provider attempt 2        transport failure  → llm_calls row, attempt=2
└── provider attempt 3        success            → llm_calls row, attempt=3
        └── plan fails validation → a *second logical* planning request (§6.2), up to 3
```

So a single turn can legitimately reach **9 provider attempts for planning alone** in the worst
case, plus up to 3 for analysis. That distinction is load-bearing in four places, and every one of
them is written against **provider attempts**, never against logical stages:

| Concern | Counted in | Where |
|---|---|---|
| Cost | one `llm_calls` row **per provider attempt** | §4.5, §7.3, §13, ET-9 |
| Rate limits | provider attempts per turn (worst case 12, typical 2) | §4.5 |
| Latency / p95 | wall time across all attempts, bounded by the turn deadline | §5 |
| Trace | **twelve stage events per turn, at most one each**; attempt counts live in `detail`, not in extra stages | §8.1 |

Every attempt is made through the Model Router, never by an agent holding a vendor SDK (FR-040).

**The orchestrator never asks a model what to do next.** It asks for a plan once, validates it, and
then executes a fixed pipeline. That is what §33.2 means by "does not pretend to think", and it is
also this architecture's strongest prompt-injection control in M1 (§9.4).

### 1.2 Components

```
                                  ┌─────────────────────────────────────────┐
  browser  ── HTTP/JSON ──────────▶│ api/            FastAPI routers         │
  localhost:3000                   │  auth · chat · events(SSE) · trace      │
           ◀── SSE stage events ───│  middleware: CORS, request ctx, session │
                                   └───────────────┬─────────────────────────┘
                                                   │
                                   ┌───────────────▼─────────────────────────┐
                                   │ core/conversations   Conversation Gateway│
                                   │  load/create conversation, persist msgs  │
                                   └───────────────┬─────────────────────────┘
                                                   │
     ┌─────────────────────────────────────────────▼──────────────────────────────────┐
     │ core/orchestrator          CENTRAL ORCHESTRATOR  (deterministic)                │
     │   turn.py  ─ the 12-stage pipeline                                              │
     │   plan_schema.py · plan_models.py · plan_validator.py  ─ the privileged gate     │
     │   ┌──────────────┬───────────────┬───────────────┬───────────────┬────────────┐ │
     │   │ core/tasks   │ core/workflows│ core/memory   │ core/trace    │ core/audit │ │
     │   └──────────────┴───────────────┴───────────────┴───────────────┴────────────┘ │
     └───────┬─────────────────────────────────────────────────┬──────────────────────┘
             │                                                 │
   ┌─────────▼──────────┐                          ┌───────────▼─────────────┐
   │ core/routing       │  MODEL ROUTER            │ core/agent_framework    │
   │  capability→model  │                          │  registry · runner      │
   └─────────┬──────────┘                          └───────────┬─────────────┘
             │                                                 │
   ┌─────────▼──────────┐                          ┌───────────▼─────────────┐
   │ providers/         │                          │ agents/                 │
   │  base.py (Protocol)│                          │  project_manager/       │
   │  anthropic.py      │                          │  (+ 7 more, M6)         │
   └─────────┬──────────┘                          └───────────┬─────────────┘
             │ TLS                                             │
       api.anthropic.com                          ┌────────────▼─────────────┐
                                                  │ core/permissions         │
                                                  │  ALLOW / DENY / ASK_USER │
                                                  └────────────┬─────────────┘
                                                  ┌────────────▼─────────────┐
                                                  │ core/tool_framework      │
                                                  │  ToolManager · registry  │
                                                  └────────────┬─────────────┘
                                                  ┌────────────▼─────────────┐
                                                  │ tools/github/            │
                                                  └────────────┬─────────────┘
                                                               │ TLS
                                                        api.github.com
```

`core/trace` and `core/audit` are drawn once but are called from every box: one emitter, three sinks
(§8).

### 1.3 What exists in M1 vs V1

| Component | M1 | Later |
|---|---|---|
| Conversation Gateway | create/load conversation, persist messages, single turn | streaming, history, multi-turn context (M2) |
| Model Router | capability → model from config, retry, cost | multi-factor routing, OpenAI/Codex (M3), local (V2) |
| Orchestrator | one-shot plan → single agent → single tool → answer | re-planning, multi-step, crash recovery (M4) |
| Agent framework | registry + one runner + `project_manager` | 7 more agents, delegation (M6, V2) |
| Tool framework | manager, registry, param validation, audit + 1 adapter | 8 more adapters (M6) |
| Permission engine | decision function, default-deny, config file | approval queue + UI (M5) |
| Memory | short-term (current conversation), write with source | long-term, entities, embeddings, RAG (M7) |
| Scheduler / Voice / Dashboard | **not built** | M10 / M9 / M8 |

---

## 2. Repository and package structure

### 2.1 Argument against roadmap §20

§20 proposes `core/`, `providers/`, `agents/`, `tools/`, `memory/`, `voice/` as **top-level sibling
directories** next to `apps/api/`. Adopting that literally creates four or five independent Python
import roots (`import core.orchestrator`, `import providers.claude`). That has three concrete costs
on this build:

1. `apps/api` would import from directories outside itself, so it needs either `sys.path`
   manipulation or five separate editable installs. On Windows, with a venv, that is a day-one
   friction tax for zero benefit.
2. Five roots in the global module namespace collide with any third-party package named `core`,
   `agents`, `tools` or `memory` — all four are real PyPI names.
3. Circular imports between sibling roots are undetectable by tooling until runtime.

**Verdict: adapt, not reject.** §20's *decomposition* is right and is preserved name-for-name. Only
the *rooting* changes: every Python module lives inside one installable package, `sunil`, under
`apps/api/`. `sunil.core.orchestrator`, `sunil.providers.anthropic`, `sunil.tools.github`. One
`pyproject.toml`, one `pip install -e .`, no path hacks. See **ADR-011**.

Three further deviations, each argued:

- **`core/models/` → `core/routing/`.** §20's `core/models/` is the Model Router, but `models` in a
  SQLAlchemy codebase means ORM tables (`sunil.db.models`). Two things called "models" one import
  apart is a defect generator. Renamed.
- **`core/agents/` + `agents/` → `core/agent_framework/` + `agents/`.** §20 has both; the pair is
  ambiguous. The framework (registry, runner, base types) is now unambiguously named. Same for
  `core/tools/` → `core/tool_framework/`.
- **Backend tests live at `apps/api/tests/`, not top-level `tests/`.** pytest wants one rootdir with
  one config; putting the suite beside the package it tests means `pyproject.toml` holds all pytest
  config and `pytest` just works from `apps/api`. §20's top-level `tests/` is reserved for
  cross-service e2e, created when there is a second service to cross (M2+).

`voice/` and `memory/{embeddings,retrieval,documents}` are **not created** in M1. Empty directories
are noise; they arrive with M9/M7.

### 2.2 The tree (M1)

```
C:\repo\SUNIL\
├─ apps/
│  ├─ api/
│  │  ├─ pyproject.toml            # package "sunil-api"; deps; ruff + pytest config
│  │  ├─ alembic.ini
│  │  ├─ migrations/               # versions/0001_initial.py
│  │  ├─ sunil/
│  │  │  ├─ __init__.py
│  │  │  ├─ main.py                # create_app() — FastAPI factory, middleware order
│  │  │  ├─ settings.py            # pydantic-settings; every env var; SecretStr
│  │  │  ├─ logging.py             # structlog config, JSON renderer
│  │  │  ├─ redaction.py           # secret registry + structlog processor
│  │  │  ├─ db/
│  │  │  │  ├─ base.py             # DeclarativeBase, portable column types
│  │  │  │  ├─ models.py           # all ORM tables (§7)
│  │  │  │  └─ session.py          # async engine, async_sessionmaker, get_session dep
│  │  │  ├─ api/
│  │  │  │  ├─ deps.py             # require_owner_session, require_client_header
│  │  │  │  ├─ schemas.py          # request/response Pydantic models
│  │  │  │  └─ routes/{auth,chat,events,trace,health}.py
│  │  │  ├─ core/
│  │  │  │  ├─ registry/           # YAML loaders: agents, tools, permissions, projects, models
│  │  │  │  ├─ conversations/
│  │  │  │  ├─ orchestrator/       # turn.py, plan_schema.py, plan_models.py, plan_validator.py
│  │  │  │  ├─ tasks/              # lifecycle + status events
│  │  │  │  ├─ workflows/
│  │  │  │  ├─ agent_framework/    # base.py, runner.py
│  │  │  │  ├─ tool_framework/     # base.py, manager.py
│  │  │  │  ├─ permissions/        # engine.py
│  │  │  │  ├─ routing/            # router.py, capabilities.py, pricing.py, retry.py
│  │  │  │  ├─ memory/             # short_term.py
│  │  │  │  ├─ trace/              # stages.py, context.py, emitter.py, bus.py
│  │  │  │  └─ audit/              # writer.py
│  │  │  ├─ providers/             # base.py (Protocol), anthropic.py, registry.py
│  │  │  ├─ agents/                # project_manager/
│  │  │  └─ tools/                 # github/
│  │  └─ tests/{unit,integration,exit,security}/
│  └─ web/                         # Next.js 16 App Router (§12)
├─ config/                         # agents.yaml permissions.yaml projects.yaml models.yaml tools.yaml
├─ infra/docker/                   # docker-compose.yml, Dockerfile.api
├─ scripts/                        # dev-api.ps1, dev-web.ps1, dev-check.ps1, seed-owner.py
├─ docs/  ·  .env.example  ·  README.md
```

**Config is not code.** `config/*.yaml` is deliberately outside the package: FR-084 requires agent
role/instructions/permissions to change without a code deployment, and FR-107's project mapping and
ADR-000 Q7's "the repository must be a config value, never hard-coded" both land here.

---

## 3. FastAPI layering and the async model

### 3.1 Layers

```
route handler          thin: parse → call a service → shape a response. No business logic.
  └ service            core/*: orchestrator, gateway, router, tool manager. No FastAPI imports.
      └ repository     sunil/db: SQLAlchemy queries. No business logic.
```

`core/` must not import from `sunil.api`. That is checkable and should be a lint rule
(`ruff` `flake8-tidy-imports` `banned-api`, or a single test that walks imports). Reason: the
orchestrator is invoked from an HTTP route today and from the scheduler in M10; coupling it to
`Request` would block that.

### 3.2 Async model

Everything is `async def` on a single event loop, single uvicorn worker.

- **HTTP out** (`AsyncAnthropic`, `httpx.AsyncClient`) — natively async, no thread pool.
- **DB** — SQLAlchemy 2.0 async (`create_async_engine`), `aiosqlite` or `psycopg` v3 driver.
- **CPU work** — there is none in M1 worth a thread.
- **Blocking calls are banned in `core/`.** No `time.sleep`, no `requests`, no sync file I/O in a
  request path. `await asyncio.sleep()` for backoff.
- **One worker only.** `uvicorn --workers 1`. The SSE trace bus (§8.4) is in-process; more than one
  worker silently breaks it. This is recorded as debt with its fix (Redis pub/sub) in §16.

`httpx.AsyncClient` and `AsyncAnthropic` are created **once** at app startup (lifespan context) and
reused. Creating a client per request leaks connections and adds TLS handshakes to the latency
budget.

### 3.3 Middleware order

Use the explicit constructor list, not `add_middleware` — Starlette applies the *most recently
added* middleware outermost, which is the wrong way round from how people read code and is a
recurring source of "my 401 has no CORS headers" bugs.

```python
app = FastAPI(
    middleware=[                          # outermost first, top to bottom
        Middleware(CORSMiddleware, ...),  # must be outermost: error responses need CORS headers too
        Middleware(RequestContextMiddleware),   # request_id, structlog contextvars, turn clock
        Middleware(SessionMiddleware, ...),     # signed cookie session
    ],
    lifespan=lifespan,
)
```

If CORS is not outermost, a 401 raised by an inner dependency reaches the browser without
`Access-Control-Allow-Origin`, and the frontend sees an opaque network error instead of "not logged
in". Name it in the code comment.

### 3.4 A chat turn, end to end

Stage numbers are NFR-020's twelve; they are the same names used in the trace enum, the audit table
and the SSE events.

| # | Stage | Component | Persisted |
|---|---|---|---|
| 1 | `message_received` | `api/routes/chat.py` | `messages` (user), `audit_events` |
| 2 | `context_loaded` | `core/conversations` | `audit_events` |
| 3 | `memory_retrieved` | `core/memory` | `memories` (source=request), `audit_events` |
| 4 | `model_selected` | `core/routing` | `audit_events` |
| 5 | `llm_io` | `core/routing` → `providers/anthropic` | `llm_calls` (purpose=`plan`) — **one row per provider attempt**, `audit_events` |
| 6 | `plan_created` | `core/orchestrator/plan_validator` | `plans`, `tasks`, `workflows`, `audit_events` |
| 7 | `agent_started` | `core/agent_framework/runner` | `task_status_events`, `audit_events` |
| 8 | `tool_requested` | `agents/project_manager` → `core/tool_framework` | `audit_events` |
| 9 | `permission_decision` | `core/permissions` | `tool_calls` (decision), `audit_events` |
| 10 | `tool_result` | `tools/github` | `tool_calls` (result), `audit_events` |
| 11 | `agent_result` | `agents/project_manager` — the *analysis* logical request | `llm_calls` (purpose=`analysis`) — one row per provider attempt, `audit_events` |
| 12 | `final_response` | `core/orchestrator` — **no LLM call in M1** (ADR-015); the agent's summary is persisted as the assistant message | `messages` (assistant), `audit_events` |

Every stage passes through **one** function, `TraceContext.emit(stage, detail=...)`, which writes a
structured log line, an `audit_events` row, and an SSE event. That is why NFR-020/ET-6 is provable
rather than aspirational: there is no second way to advance a stage.

**Each of the twelve stages is emitted at most once per turn.** Retries — provider attempts *and*
whole re-planning attempts — do **not** emit extra stage events; they are recorded as `llm_calls`
and `plans` rows and surface in the emitting stage's `detail` (`detail.provider_attempts`,
`detail.plan_attempts`). Without that rule a retried turn would emit fourteen stage rows and ET-6's
"all twelve, in order" assertion would become ambiguous. QA may therefore assert both *presence*
and *uniqueness*.

Failure paths short-circuit the pipeline and set a terminal `outcome`, but **always emit stage 12**
with the failure kind, so the trace is complete for a failed turn too (ET-8).

---

## 4. The Model Router

### 4.1 The rule

`ROADMAP.md` §5 / §33.1: no agent, orchestrator or tool names a vendor. Callers name a
**capability**. Enforced two ways: (a) `providers/` is the only package permitted to
`import anthropic` — one lint rule, one test that greps the tree (FR-040's own acceptance criterion
is exactly this); (b) `ModelRouter.run()` takes no model or provider argument.

### 4.2 Provider interface

```python
# sunil/providers/base.py
class LLMPurpose(StrEnum):
    PLAN = "plan"; ANALYSIS = "analysis"
    FINAL_RESPONSE = "final_response"    # defined; NOT used by any M1 code path (ADR-015).
                                         # M1 writes llm_calls rows with purpose ∈ {plan, analysis} only.

@dataclass(frozen=True)
class ChatTurn:      role: Literal["user", "assistant"]; content: str

@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: list[ChatTurn]
    max_tokens: int
    json_schema: dict | None = None    # None → free text; set → structured output demanded
    temperature: float | None = None
    effort: str | None = None          # passed through verbatim when set
    stop_sequences: list[str] | None = None

@dataclass(frozen=True)
class LLMResponse:
    text: str | None                   # None when json_schema was requested
    data: dict | None                  # populated ONLY on a schema-conformant parse
    provider: str; model: str
    input_tokens: int; output_tokens: int
    stop_reason: str | None
    provider_request_id: str | None
    latency_ms: int

@dataclass(frozen=True)
class ModelCapabilities:
    context_window: int; max_output: int
    supports_structured_output: bool
    input_usd_per_mtok: Decimal; output_usd_per_mtok: Decimal

class LLMProvider(Protocol):
    name: str
    def capabilities(self, model: str) -> ModelCapabilities: ...
    async def generate(self, model: str, request: LLMRequest) -> LLMResponse: ...
```

Errors are normalised to SUNIL's own hierarchy at the provider boundary, so retry policy is written
once and does not import vendor exception types:

```python
class ProviderError(Exception): ...
class ProviderTransientError(ProviderError): ...    # retryable
class ProviderPermanentError(ProviderError): ...    # not retryable
class StructuredOutputError(ProviderPermanentError): ...
```

### 4.3 The Anthropic provider — verified surface

Verified against the live Anthropic documentation on 2026-08-14. **Do not substitute a parameter
that is not on this list.**

- Package `anthropic` (PyPI, current 0.122.0; requires Python ≥3.9 — fine on 3.13).
- `from anthropic import AsyncAnthropic`; constructed once at startup with
  `api_key=settings.anthropic_api_key.get_secret_value()`, `max_retries=0`, `timeout=<per-capability>`.
  **`max_retries=0` is deliberate**: SUNIL owns retry so each attempt is individually persisted and
  countable (FR-045 requires the retry count to be visible).
- `await client.messages.create(model=..., max_tokens=..., system=..., messages=[...])`.
- **Structured output:** `output_config={"format": {"type": "json_schema", "schema": {...}}}`.
  No beta header is required. (The older `output_format` parameter and the
  `structured-outputs-2025-11-13` beta header still work during a transition period — do not use
  them.) Structured output is enforced by **constrained decoding**, so a conformant response is the
  API's guarantee, not a hope. SUNIL still re-validates — see §6.
  The SDK also offers `client.messages.parse(..., output_format=<PydanticModel>)` returning
  `.parsed_output`; M1 uses `create()` + explicit validation instead, because the fail-closed design
  needs its own validation step regardless and `create()` is the surface documented for the async
  client.
- **Usage:** `message.usage.input_tokens`, `message.usage.output_tokens`.
- **Provider request id:** `message._request_id` (public despite the underscore).
- **Errors:** `anthropic.APIConnectionError`, `anthropic.APITimeoutError`, `anthropic.RateLimitError`
  (429), `anthropic.InternalServerError` (≥500) → `ProviderTransientError`.
  `anthropic.BadRequestError` (400), `AuthenticationError` (401), `PermissionDeniedError` (403),
  `NotFoundError` (404), `UnprocessableEntityError` (422) → `ProviderPermanentError`.

**JSON Schema features usable with `output_config`** (verified): `object`/`array`/`string`/`integer`/
`number`/`boolean`/`null`, `enum` (strings, numbers, bools, nulls), `const`, `anyOf`, `allOf`,
internal `$ref`/`$defs`, `default`, `required`, `additionalProperties: false`, string `format`,
array `minItems` of 0 or 1.
**Not supported:** recursive schemas, external `$ref`, numeric bounds (`minimum`/`maximum`),
string length bounds (`minLength`/`maxLength`), other array constraints, `additionalProperties`
anything other than `false`. The plan schema in §6 stays inside this envelope by construction; the
constraints the schema cannot express (`confidence` in 0..1) are enforced by Pydantic afterwards.

### 4.4 Model catalogue

Verified model IDs, context and price (USD per million tokens):

| Model ID | Alias | Context | Max output | Input $/MTok | Output $/MTok | Structured output |
|---|---|---|---|---|---|---|
| `claude-opus-5` | `claude-opus-5` | 1M | 128k | 5 | 25 | yes |
| `claude-sonnet-5` | `claude-sonnet-5` | 1M | 128k | 2 | 10 | yes |
| `claude-fable-5` | `claude-fable-5` | 1M | 128k | 10 | 50 | yes |
| `claude-haiku-4-5-20251001` | `claude-haiku-4-5` | 200k | 64k | 1 | 5 | yes |

Model IDs are **pinned snapshots**, including the dateless ones — `claude-opus-5` is not an evergreen
pointer. Pricing is copied into `config/models.yaml` with a `pricing_version` date so a future price
change never silently rewrites historical cost records.

`effort` exists as a request parameter and defaults to `high` on Opus 5 and Sonnet 5 on the Claude
API. M1 does not set it. If §5's latency budget proves tight, the capability config may pass an
`effort` value through verbatim — take the permitted values from the Effort documentation at that
time; **do not guess them.**

### 4.5 Selection, retry and escalation

```python
async def run(self, *, capability: Capability, request: LLMRequest,
              purpose: LLMPurpose, ctx: TraceContext,
              privacy_level: PrivacyLevel = PrivacyLevel.INTERNAL,
              cost_priority: CostPriority = CostPriority.BALANCED) -> LLMResponse
```

This matches §5's illustrative call shape. `privacy_level` and `cost_priority` are **accepted and
recorded but not used for selection in M1** — NFR-010 requires the parameter to exist now so V2's
LOCAL-ONLY enforcement is an additive change rather than a signature break. That is stated here, in
the section that owns it, and repeated nowhere as a claim of enforcement.

Selection in M1 is a config lookup: `capability → {provider, model, max_tokens, timeout_s}` from
`config/models.yaml`. Multi-factor routing (cost, latency, historical success) is M3/V2 by SRS §1.3.

Retry (FR-045, NFR-070, ADR-000 Q6):

- **3 provider attempts max per logical request**, backoff `1s, 2s, 4s` with full jitter
  (`sleep = random()*base`), on `ProviderTransientError` only.
- **The turn deadline is checked before each attempt (§5.3).** If the attempt's own timeout exceeds
  the remaining budget, the attempt is not started and the router raises immediately. A retry that
  cannot finish is not a retry, it is a way to blow the latency budget quietly.
- `ProviderPermanentError` fails immediately — retrying a 400 wastes the latency budget.
- **Every attempt writes its own `llm_calls` row** with `attempt` and `error_kind`. That is how
  FR-045's "the retry count is visible in the logs" is satisfied by data rather than by a log string,
  and it is why cost and rate-limit arithmetic are done over attempts, never over stages (A-2).
- On exhaustion, the router raises; the orchestrator produces the `provider_error` outcome (§11.3)
  and stage 12 still fires.

**Escalation** in M1 is capability-level, not automatic: an agent declares
`preferred_capability: general_reasoning` and `escalation_capability: complex_reasoning`; the runner
uses the escalation capability when the agent's own logic asks for it. No automatic quality-based
escalation exists in M1 — that needs the evaluation data §27 describes, which does not exist yet.

### 4.6 Adding a provider without touching agents

1. Write `sunil/providers/openai.py` implementing `LLMProvider`.
2. Register it: one line in `sunil/providers/registry.py`.
3. Add its models + pricing to `config/models.yaml`.
4. Point a capability at it in the same file.

Zero changes to `core/orchestrator`, `core/agent_framework`, `agents/*` or `tools/*`. That is the
test of §33.1 and it should be asserted by a test that constructs the router with a fake provider
and runs a full turn.

---

## 5. Latency budget (NFR-060: ≤30 s p95)

Re-derived after A-2 (provider attempts, not logical stages) and A-4 (two logical stages, not
three). **The old table's 11–24 s counted one attempt per stage and silently assumed no retry ever
happens.** It does not survive contact with a rate limit.

### 5.1 The nominal turn — every logical request succeeds on its first provider attempt

| Step | Model | Budget |
|---|---|---|
| Plan — 1 provider attempt (structured, ~600 out) | `claude-sonnet-5` | 3–7 s (the first call after a schema change pays a one-off grammar-compilation cost; compiled grammars cache ~24 h) |
| GitHub read (3 endpoints, concurrent) | — | 0.5–2 s |
| Analysis — 1 provider attempt (~500 out), **this is also the user-facing answer** | `claude-sonnet-5` | 4–8 s |
| DB + overhead | — | <0.5 s |
| **Nominal total** | | **7.5–17.5 s** |

Removing the third call (ADR-015) took 3–6 s off the nominal path, which is the headroom that pays
for the retry case below.

### 5.2 What a retry actually costs

| Case | Added | Turn total |
|---|---|---|
| 1 transient provider retry (backoff base 1 s, full jitter → avg 0.5 s) + a fresh attempt | +3.5–7.5 s | 11–25 s |
| 2 transient retries (1 s + 2 s bases, avg 1.5 s of sleep) + 2 fresh attempts | +7.5–15.5 s | 15–33 s |
| 1 plan-validation retry (a whole second **logical** planning request) | +3–7 s | 10.5–24.5 s |
| Worst legal case: 3 logical plan requests × 3 provider attempts, then analysis | — | **far past 30 s** |

**Honest statement of NFR-060.** ≤30 s p95 holds **only if fewer than 5% of turns need more than one
extra provider attempt.** That is a claim about Anthropic's transient-error rate on this account,
not about SUNIL's code, and M1 cannot prove it — five timed runs (T20) measure a median and a max,
not a 95th percentile. So NFR-060 is reported in M1 as *"median and max of N observed turns against
a 30 s target, with the attempt count for each"*, and true p95 needs the sample size that M11's
soak testing provides. Anything else would be arithmetic theatre.

### 5.3 The turn deadline — new, and it closes a real gap

`M1_CHAT_SPEC` §5.3 has the browser abandon a turn at **45 s**. Nothing on the server knew that
number, so a retrying turn could keep working — and keep spending — after the only user had been
shown a timeout error, and the turn's own failure would never be recorded as a failure.

**Decision: a monotonic per-turn deadline of `SUNIL_TURN_DEADLINE_S` (default 40 s), started by
`RequestContextMiddleware` and carried on `TraceContext`.**

- The Model Router checks the remaining budget **before starting any attempt** and refuses to start
  one whose own timeout exceeds what is left. A retry that cannot finish is not attempted.
- On breach, the turn ends deterministically: outcome `failed`, `failure.kind = provider_error`
  (no new failure kind, so the frozen §6 contract and the Designer's four `ErrorCard` variants are
  untouched), `error_kind = turn_deadline_exceeded` in the trace detail and on the `tasks` row, and
  **stage 12 still fires** (ET-8).
- 40 < 45 by design: the server always produces a persisted, traced failure *before* the client
  gives up, so a timeout is never invisible on the server side.

`claude-sonnet-5` is the M1 default for both live capabilities — it is the documented best
speed/intelligence trade and at $2/$10 per MTok it keeps the whole $150 budget comfortable.
`claude-opus-5` is wired to `complex_reasoning` and is not on the M1 hot path. Opus calls with
`effort: high` would put the 30 s target at genuine risk; that is the reason, stated so it is not
rediscovered.

---

## 6. Structured-output enforcement — the most important control in M1

Requirement: §25, NFR-040/041, FR-061/062, **ET-7**. Goal: *an invalid plan can never reach a tool*,
and that must be provable by a test rather than asserted.

### 6.1 Five layers, each independently sufficient to stop execution

**Layer 1 — the schema is generated from the registries, at runtime.**
`plan_schema.build_plan_schema(agents, tools, projects, actions)` emits JSON Schema whose `agents`,
`tools`, `project_key` and `steps[].action` fields are `enum`s populated from the live registries.
Because the Anthropic API enforces the schema by constrained decoding, **the model cannot emit an
agent or tool name that is not registered** — the token sequence is not reachable. The whitelist is
not a post-hoc filter; it is part of the grammar.

```jsonc
{
  "type": "object", "additionalProperties": false,
  "required": ["intent","confidence","privacy_level","objective","project_key","agents","tools","steps"],
  "properties": {
    "intent":        {"type":"string","enum":["project_status_review","unsupported"]},
    "confidence":    {"type":"number"},
    "privacy_level": {"type":"string","enum":["internal"]},
    "objective":     {"type":"string"},
    "project_key":   {"type":"string","enum":["easy_clean_workforce","__unknown__"]},   // from config/projects.yaml + sentinel
    "agents":        {"type":"array","items":{"type":"string","enum":["project_manager"]}},
    "tools":         {"type":"array","items":{"type":"string","enum":["github"]}},
    "steps":         {"type":"array","items":{
        "type":"object","additionalProperties":false,
        "required":["id","action"],
        "properties":{
          "id":     {"type":"string"},
          "action": {"type":"string","enum":["resolve_project","load_recent_activity","summarise_activity"]},
          "tool":   {"type":"string","enum":["github","none"]}
        }}}
  }
}
```

Note the two sentinels. `project_key: "__unknown__"` is how **ET-11** is satisfied structurally: an
unrecognised project name has a legal, non-executing representation, so the model does not have to
invent an identifier. `tool: "none"` avoids a nullable union type, which is outside the verified
schema-feature envelope (§4.3).

**Layer 2 — the provider refuses to guess.** `AnthropicProvider.generate()` returns
`LLMResponse.data` only if a `json_schema` was requested *and* the response body parsed as JSON.
Anything else raises `StructuredOutputError`. It never returns half-parsed data, never falls back to
regex, never strips markdown fences and retries. NFR-041 is a property of this one method.

**Layer 3 — Pydantic.** `PlanDraft` with `model_config = ConfigDict(extra="forbid")` re-validates
types, enum membership, `0.0 ≤ confidence ≤ 1.0`, non-empty `steps`, and unique `steps[].id`. This
catches everything the JSON Schema could not express (§4.3) and everything a *future* provider
without constrained decoding would get wrong.

**Layer 4 — registry re-check.** `validate_plan(draft, registries) -> ValidatedPlan` independently
confirms that every agent, tool, action and project in the draft exists **now**, and that the named
agent is actually granted the named tools in `config/permissions.yaml`. Layer 1 and Layer 4 are
deliberately redundant: Layer 1 is the provider's guarantee, Layer 4 is ours. If Anthropic ever
serves a stale compiled grammar, or a provider is swapped, Layer 4 still holds.

**Layer 5 — a validated type, enforced at runtime.** *(Amended per A-3. The earlier text called this
"unforgeable" and claimed "no expressible code path from raw LLM output to a tool adapter". Both
claims are withdrawn: they are too strong for Python. Type annotations are erased at runtime,
`__slots__` does not stop `object.__new__(ValidatedPlan)`, and a module-private token is reachable
through the module's `__dict__` by any code that imports it. The design is unchanged and remains
correct; only the claim is now accurate — and the enforcement it needed is now written down.)*

```python
# sunil/core/orchestrator/plan_models.py
_VALIDATOR_TOKEN = object()          # module-private; never exported

class ValidatedPlan:
    __slots__ = ("intent","objective","project_key","agent","tools","steps","plan_id","raw")
    def __init__(self, *, _token: object, **fields: Any) -> None:
        if _token is not _VALIDATOR_TOKEN:
            raise TypeError(
                "ValidatedPlan may only be constructed by plan_validator.validate_plan()"
            )
        ...
```

`validate_plan()` is the only code that holds `_VALIDATOR_TOKEN`, so no *accidental* construction
compiles into existence and every downstream signature demands the type. What makes that a control
rather than a convention is the guard, which is checked on the execution path itself:

```python
# sunil/core/orchestrator/guards.py
class InvalidPlanExecution(Exception): ...

def require_validated_plan(plan: object) -> ValidatedPlan:
    if not isinstance(plan, ValidatedPlan):
        raise InvalidPlanExecution(
            f"execution requires a ValidatedPlan, received {type(plan).__name__}"
        )
    return plan
```

`require_validated_plan()` is the **first statement** of `execute_plan()`, of the agent runner, and
of `ToolManager.execute()`. Three call sites, one function, and a test per site.

**Trusted execution metadata.** Privilege does not travel on a type alone; it travels on a value
that only the orchestrator can mint:

```python
@dataclass(frozen=True)
class ExecutionMetadata:
    validated_plan_id: str     # == the `plans` row written with validated = true
    request_id: str
    task_id: str
    agent_id: str
```

`ToolManager.execute(tool, operation, params, meta: ExecutionMetadata)` requires it, all four fields
are written onto the `tool_calls` row, and the agent runner constructs it from the `ValidatedPlan`
and the `Task` — an agent never builds one. A tool call is therefore traceable to the exact
validated plan that authorised it, which is also what makes the audit trail answer *"which plan
caused this call?"* without inference.

**Stored-plan verification (specified now, lands with M5).** The Tool Manager can additionally
re-read `plans` by `meta.validated_plan_id` and refuse to execute unless the stored row carries
`validated = true`. Inside a single M1 turn this is genuinely redundant — the same process validated
the plan seconds earlier and holds it in memory — so implementing it now would buy a DB round trip
and no security. It stops being redundant the moment validation and execution are separated by a
process boundary or by time: **M5's approval queue** (a human approves at T+10 minutes) and **M10's
scheduler** (a worker executes a plan it did not validate). It is therefore recorded as deferred
control **DC-14**, owned by M5, with the metadata seam built in M1 so it is a ten-line addition and
not a refactor.

**The full chain, as the owner's review §7 specifies it:**

```
LLM output
   ↓ schema validation      (constrained decoding — layer 1)
   ↓ Pydantic validation    (layer 3)
   ↓ registry validation    (layer 4)
   ↓ ValidatedPlan          (layer 5, minted only by validate_plan())
   ↓ runtime execution guard        require_validated_plan()  → InvalidPlanExecution
   ↓ agent permission check         the agent's own config/agents.yaml grant (FR-082)
   ↓ tool parameter validation      params_model, extra="forbid" (FR-102)
   ↓ permission engine              default-deny decide() (FR-120)
   ↓ tool adapter
```

### 6.2 Retry and failure

Up to **3 plan attempts** (ADR-000 Q6). Each attempt writes a `plans` row with `raw_json`,
`validated`, `validation_errors` and `attempt` — so a rejected plan is evidence, not a lost log line,
and it feeds §30's training capture. Attempts 2 and 3 append the previous validation errors to the
prompt as corrective context. On exhaustion: terminal outcome `plan_rejected`, stage 12 emitted,
**zero `tool_calls` rows**, and the frontend renders M1_CHAT_SPEC §5.8.

### 6.3 The tests that make this provable

| Test | Asserts |
|---|---|
| `test_validated_plan_cannot_be_constructed_directly` | `TypeError` raised |
| `test_execute_plan_rejects_a_dict` | `InvalidPlanExecution`, no DB writes |
| `test_run_agent_rejects_a_non_validated_plan` | `InvalidPlanExecution` at the agent runner (guard site 2) |
| `test_tool_manager_requires_execution_metadata` | `ToolManager.execute()` refuses a call with no `ExecutionMetadata` (guard site 3) |
| `test_tool_call_row_carries_validated_plan_id` | all four `ExecutionMetadata` fields land on the `tool_calls` row |
| `test_plan_schema_enums_match_registries` | schema builder output == registry keys |
| `test_unknown_agent_in_plan_is_rejected` | `PlanRejected`, zero tool calls (FR-061) |
| `test_malformed_llm_output_creates_zero_tool_calls` | **ET-7** — `SELECT count(*) FROM tool_calls == 0` |
| `test_three_failed_plans_return_plan_rejected_outcome` | FR-062, user-visible failure, zero tool calls |

Nine tests, three of them new with A-3. Deleting any one of them deletes the control it proves.

---

## 7. Data model

### 7.1 Storage decision in one line

PostgreSQL 17 + pgvector is the **V1 target**; **SQLite is the M1 default** for dev, test and the exit
run, because Docker's daemon is down, this machine has no native Postgres, and M1 is due in three
days (ADR-001). One schema, one Alembic history, portable column types, `DATABASE_URL` switches
between them. **M1 requires no pgvector and no Redis at all** — see §7.5 and ADR-005/ADR-013. This
removes Docker from M1's critical path entirely.

### 7.2 Portability rules (non-negotiable — they are what make one schema serve both)

| Concern | Rule | Why |
|---|---|---|
| Primary keys | `String(36)`, UUID4 as text, generated in Python | SQLite has no UUID type; text IDs are greppable in logs |
| JSON | `sa.JSON().with_variant(postgresql.JSONB, "postgresql")` | JSONB on PG, TEXT-backed JSON on SQLite, one column definition |
| Timestamps | `DateTime(timezone=True)`, always written as `datetime.now(UTC)` | SQLite drops tzinfo; writing UTC everywhere makes that harmless |
| Money | `BigInteger` **micro-USD** (`cost_micro_usd`) | `Numeric` on SQLite is lossy and warns; integers are exact. Format as dollars at the API edge only |
| Enums | `String` + a Python `StrEnum` + a `CheckConstraint` | native `ENUM` types are a Postgres-only migration headache |
| Booleans | `Boolean` | fine on both |
| Server defaults | **none** — all defaults set in Python | server-side `now()` differs between engines |

### 7.3 Tables (M1 migration `0001_initial`)

All tables carry `id String(36) PK`. `request_id String(36)` is indexed on every table that has it —
it is the join key for NFR-020/ET-6.

**`users`** — `name`, `username` (unique), `password_hash` (scrypt, encoded params+salt+digest),
`preferences` JSON `{}`, `security_settings` JSON `{}`, `created_at`.
One row in V1 (ADR-000 Q3). `user_id` is threaded everywhere so V2 adds users without a re-model.

**`conversations`** — `user_id` FK, `title` nullable, `active_context` JSON nullable, `created_at`,
`updated_at`.

**`messages`** — `conversation_id` FK, `seq` int, `role` (`user|assistant|system`), `content` Text,
`request_id` nullable, `model_used` nullable, `tokens_in` nullable, `tokens_out` nullable,
`cost_micro_usd` nullable, `created_at`. Index `(conversation_id, seq)`.
Message is a **child table, not an embedded array** — SRS Q8 left this to the Architect. A table
gives per-message cost columns (FR-046), a stable `seq` for ordering, and cheap
`WHERE request_id = ?` retrieval; an embedded array would force a full-document rewrite per turn and
make ET-9's per-call cost query awkward.

**`workflows`** — `owner_user_id` FK, `trigger` (`chat_message`), `status`, `schedule` JSON nullable
(always null until M10), `request_id`, `created_at`, `completed_at` nullable.

**`tasks`** — `workflow_id` FK, `conversation_id` FK, `request_id`, `objective` Text, `status`
(`pending|in_progress|completed|failed`), `priority` (default `normal`), `parent_task_id` nullable
(always null in M1), `assigned_agent` (agent key from `config/agents.yaml`), `privacy_level`
(default `internal`, not enforced), `model_used` nullable, `created_at`, `started_at` nullable,
`completed_at` nullable, `failure_kind` nullable.

**`task_status_events`** — `task_id` FK, `from_status` nullable, `to_status`, `at`.
FR-065 asks for a status *history* with ordered timestamps; a single mutable `status` column cannot
answer that, so transitions are events and `tasks.status` is the materialised latest value.

**`plans`** — `request_id`, `task_id` FK nullable, `attempt` int, `schema_version`, `raw_json` JSON,
`validated` bool, `validation_errors` JSON nullable, `created_at`. (ET-2, §30.)

**`tool_calls`** — `request_id`, `task_id` FK, `agent_id` str, `tool`, `operation`, `parameters` JSON,
`permission_decision` (`allow|deny|ask_user`), `permission_reason`, `status` (`ok|error|not_executed`),
`result` JSON nullable, `error_kind` nullable, `duration_ms`, `created_at`. (§21, FR-103, ET-4.)

**`approvals`** — `request_id`, `task_id` FK nullable, `tool_call_id` FK nullable, `action`, `risk`,
`requested_by`, `status` (`pending|approved|rejected`), `user_decision` nullable, `requested_at`,
`decided_at` nullable.
Created in `0001` but **no M1 code path writes it** (ADR-000 Q4). Building the table now costs ten
lines and saves M5 a migration; the threat model records that it is empty by design so nobody reads
its emptiness as a passing control.

**`memories`** — `user_id` FK, `type` (`short_term|long_term|structured|knowledge|preference`),
`content` Text, `source_request_id`, `source_task_id` nullable, `relevance` float nullable,
`sensitivity` (**non-null**, default `internal` — NFR-009), `created_at`.
**No `embedding` column in M1** (ADR-013). Adding a `vector` column is additive; adding it now would
make the schema Postgres-only and put Docker back on the critical path for zero M1 benefit
(FR-143 is COULD/M7).

**`llm_calls`** — one row **per provider attempt** (A-2). `request_id`, `task_id` FK nullable,
`agent_id` nullable, `purpose` (`plan|analysis|final_response` — M1 writes only the first two,
ADR-015), `capability`, `provider`, `model`, `attempt` int,
`request_system` Text, `request_messages` JSON, `request_schema` JSON nullable, `response_text` Text
nullable, `response_json` JSON nullable, `stop_reason` nullable, `input_tokens`, `output_tokens`,
`cost_micro_usd`, `pricing_version`, `latency_ms`, `error_kind` nullable, `provider_request_id`
nullable, `created_at`.
This single table satisfies FR-046, NFR-030, ET-9, §28's "LLM input/output" stage and most of §30.
All content is passed through the redaction processor (§9.2) **before** insert.

**`audit_events`** — `request_id`, `seq` int, `stage` (the twelve NFR-020 names), `task_id` nullable,
`actor` (component name), `summary`, `detail` JSON, `at`. Unique `(request_id, seq)`.
This is the table ET-6 is graded against.

**`agents` is deliberately not a table.** FR-084 requires agent configuration to change without a
code deployment; `config/agents.yaml` is that source of truth. A table would duplicate it and create
a synchronisation bug. `tool_calls.agent_id` and `tasks.assigned_agent` store the YAML key. Startup
validates that every agent referenced in `permissions.yaml` exists in `agents.yaml` and refuses to
boot otherwise. This is a deliberate deviation from §21's "Agent" object — the object exists, as a
config schema (§10.2).

### 7.3.1 Capture-policy columns (A-6, ADR-014)

Five tables hold content that V3 may one day train on. Each of them carries the same four columns,
written at insert time by one resolver (§13.2), never back-filled by guesswork later:

| Column | Type | Values |
|---|---|---|
| `capture_policy` | `String` + `CheckConstraint` | `none` · `metadata_only` · `redacted_full` · `full_local_only` |
| `sensitivity` | `String`, **non-null** | `public` · `internal` · `confidential` · `restricted` |
| `retention_class` | `String`, non-null | `transient` · `standard` · `long` · `permanent` |
| `training_eligible` | `Boolean`, non-null | derived, never hand-set (§13.2) |

Applied to: **`messages`, `plans`, `llm_calls`, `tool_calls`, `memories`** (which already carried
`sensitivity` for NFR-009; it gains the other three).

**Deliberately *not* applied to `audit_events`.** The audit trail is an operational and security
record, not a training corpus. A capture policy must never be able to suppress an audit row —
ET-6 grades the completeness of that table, and a policy that could empty it would be a control
that disables a control. `audit_events.detail` remains redacted (§8.3), and under a restrictive
policy the *excerpts* inside `detail` are omitted while every stage row still exists.

### 7.4 Migrations

Alembic, single linear history, `0001_initial` for M1.

- Autogenerate is a **draft**, never a commit — SQLite reflection misses constraints. Every revision
  is hand-reviewed.
- `downgrade()` is implemented, so the test suite can round-trip.
- **Never edit a merged revision.** Corrections are new revisions (my standing convention: a
  decision that changes another decision is a new record, not a silent edit).
- `alembic upgrade head` is an explicit step (`scripts/dev-api.ps1` runs it). The app **does not**
  auto-migrate at startup; it *asserts* the `alembic_version` matches head and refuses to boot
  otherwise. Fail fast beats a half-migrated database.
- Before Gate 3, the migration must be run once against real PostgreSQL. Recorded as debt in §16 —
  SQLite-only verification is the accepted risk of the M1 date.

### 7.5 Where pgvector fits, and whether M1 needs it

It does not. M1 writes exactly one memory type (`short_term`, FR-140/144) and performs no similarity
search. pgvector arrives with **M7** (FR-143), as one migration adding `memories.embedding vector(N)`
plus an index, once the embedding model and dimension are chosen. Because M1 stores no embeddings,
that migration is purely additive. ADR-013.

---

## 8. Observability

### 8.1 One emitter, three sinks

```python
class TraceStage(StrEnum):
    MESSAGE_RECEIVED="message_received"; CONTEXT_LOADED="context_loaded"
    MEMORY_RETRIEVED="memory_retrieved"; MODEL_SELECTED="model_selected"
    LLM_IO="llm_io";                     PLAN_CREATED="plan_created"
    AGENT_STARTED="agent_started";       TOOL_REQUESTED="tool_requested"
    PERMISSION_DECISION="permission_decision"; TOOL_RESULT="tool_result"
    AGENT_RESULT="agent_result";         FINAL_RESPONSE="final_response"

class TraceContext:
    request_id: str; user_id: str; conversation_id: str
    started_at: float; seq: int
    async def emit(self, stage: TraceStage, *, summary: str, detail: dict | None = None,
                   task_id: str | None = None) -> None:
        # 1. structlog JSON log line
        # 2. audit_events row  (seq += 1)
        # 3. TraceBus.publish  (SSE)
```

Twelve stages, one call site each. NFR-020 is then a query, not a hope:

```sql
SELECT stage, seq, at FROM audit_events WHERE request_id = :rid ORDER BY seq;
-- ET-6 passes iff this returns all twelve, in the enum's order, none missing.
```

A test asserts `set(stages_emitted) == set(TraceStage)` for a successful turn, and that a failed turn
still ends on `final_response`.

### 8.2 Log format (FR-008)

`structlog` with `JSONRenderer`, `contextvars` for `request_id`. Every line carries at minimum
`timestamp` (ISO-8601 UTC), `request_id`, `component`, `level`, `event` — plus `stage` when it comes
from the emitter. Uvicorn's own access/error loggers are routed into the same processor chain so
there is one log format, not two.

**Untrusted content is never interpolated into a log message string.** It goes in a field
(`detail.tool_result_excerpt`), truncated. A log message built by f-string from external text is a
log-injection vector and it wrecks JSON greppability.

### 8.3 Secret redaction as a mechanism (ET-10, NFR-001/005)

Promises do not redact. Two mechanisms do:

1. **A value registry.** `settings.py` registers every loaded secret's *value* with
   `redaction.register(value)` at startup: the Anthropic key, the GitHub PAT, the session secret,
   the DB URL's password. Registration happens once, in one place.
2. **A structlog processor + a persistence hook.** `redaction.scrub(obj)` walks strings, dicts and
   lists and (a) replaces any registered secret value with `«redacted:anthropic_api_key»`, (b)
   replaces the value of any key matching `api_key|apikey|authorization|token|secret|password|cookie`
   (case-insensitive) with `«redacted»`, (c) replaces anything matching high-signal patterns
   (`sk-ant-[A-Za-z0-9_-]{10,}`, `gh[pousr]_[A-Za-z0-9]{20,}`, `Bearer [A-Za-z0-9._-]{20,}`).
   The processor runs on every log line; `scrub()` also runs on `llm_calls.request_messages`,
   `llm_calls.response_*`, `tool_calls.parameters`, `tool_calls.result` and `audit_events.detail`
   **before insert**.

Secrets are never placed in a prompt in the first place (§9.1) — redaction is the second line, and
the one that is testable: `test_registered_secret_never_appears_in_log_output` and
`test_registered_secret_never_appears_in_persisted_llm_call` are ET-10.

### 8.4 The progress channel (SSE) — the Designer's escalation #1

**Decision: M1 ships a real one-way stage-event channel. ADR-009.**

Rationale in one sentence: the twelve events are already produced, timestamped and persisted for
NFR-020, so publishing them to an in-process bus and rendering them as SSE is roughly 90 lines of
code — cheaper than the client-side timed approximation is *honest*, and a fabricated progress
display contradicts §33.10 in a product whose whole selling point is observability.

**It is cosmetic by construction.** The chat POST is unchanged: still synchronous, still returns the
full answer in its own response (FR-020). If the SSE connection never opens, drops, or the whole
feature is switched off with `SUNIL_PROGRESS_EVENTS=false`, the turn completes identically and the
answer still arrives. That is what makes it a safe thing to build three days out — and it is why
ADR-009 also names it the **designated descope lever**: if the M1 date comes under pressure, T12 is
dropped, the flag goes false, and the frontend falls back to the deterministic client-side stepper
the Designer already specified in M1_CHAT_SPEC §5.3. No redesign, no renegotiation.

**Status after the owner's review: T12 is pre-classified OPTIONAL / post-M1** (review §14). It is
built only if the vertical slice is green with time to spare. `SUNIL_PROGRESS_EVENTS` therefore
ships defaulting to **`false`**, and is flipped to `true` the moment T12 lands.

Mechanics:

- `GET /api/v1/chat/{request_id}/events`, `text/event-stream`.
- **The browser generates the `request_id`** (UUID4) and sends it both as the `X-Request-Id` header
  on the POST and in the SSE path. FR-004's acceptance criterion already permits an accepted-if-
  supplied ID. The server validates it is a well-formed UUID4 and rejects anything else with 422.
- **Race is handled by design, not by ordering.** `TraceBus` holds, per `request_id`: the owning
  `user_id`, a bounded replay buffer (64 events), a set of subscriber queues, and a TTL (5 min).
  Whoever arrives first — POST or SSE — creates the channel and claims ownership; the other must
  match the same `user_id` or gets 403. A late subscriber is sent the buffer, then live events. A
  turn with no subscriber just fills the buffer and is garbage-collected.
- Wire format, one frame per stage:
  `event: stage\ndata: {"stage":"tool_requested","offset_ms":2600,"detail":{...}}\n\n`
  plus `event: done\ndata: {"outcome":"ok"}\n\n` as the terminal frame, and a `: ping\n\n` comment
  heartbeat every 15 s so intermediaries and the client both know the stream is alive.
- Headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`.
- Server closes the stream on the terminal frame or after 120 s, whichever first.
- **The API sends `stage` only.** The 12→4 phase mapping and every human-readable label live in the
  frontend (`apps/web/src/lib/phases.ts`), because that is presentation policy the Designer owns and
  may change without a backend deploy. Same rule applies to all failure copy (§11.3).

Single-worker dependency is real and stated in §3.2 and §16.

### 8.5 The trace on a completed turn

The chat POST response carries `trace: [{stage, offset_ms, detail}]` — twelve entries — so the
Designer's `TraceDisclosure` needs no second request. `GET /api/v1/trace/{request_id}` returns the
same thing plus `llm_calls` and `tool_calls` summaries, for debugging and as the seed of M8's
NFR-021 view.

---

## 9. Security architecture

### 9.1 Secrets (§26.5, NFR-001/005, ADR-006)

- `pydantic-settings` `BaseSettings`; every secret typed `SecretStr`, so an accidental
  `repr()`/`json()` prints `**********`.
- Values come from process environment or a gitignored `.env`. `.env.example` is committed with
  **placeholder values only** and is the single inventory of what must be set (§14.4).
- Secrets are injected into **clients at construction** (`AsyncAnthropic(api_key=…)`,
  `httpx` `Authorization` header) and are never string-formatted into a prompt, a plan, a tool
  parameter, a log message, or an error. A test asserts no registered secret value appears in any
  `llm_calls.request_*` column.
- The owner supplies `ANTHROPIC_API_KEY` and `GITHUB_TOKEN` after Gate 2 (§15).

### 9.2 Permission engine (§11, FR-120/121, ADR-000 Q4)

A pure decision function, structurally default-deny:

```python
class Decision(StrEnum): ALLOW="allow"; DENY="deny"; ASK_USER="ask_user"

@dataclass(frozen=True)
class PermissionResult:
    decision: Decision; reason: str; source: str      # "config:project_manager.github.list_recent_activity" | "default-deny"

def decide(agent_id: str, tool: str, operation: str) -> PermissionResult:
    grant = CONFIG.get(agent_id, {}).get(tool, {}).get(operation)
    if grant is None:
        return PermissionResult(Decision.DENY, "no explicit grant", "default-deny")
    return PermissionResult(Decision(grant), "explicit grant", f"config:{agent_id}.{tool}.{operation}")
```

Default-deny is *structural*: the missing-key branch returns DENY. It is not a config value that
could be set wrong, and `test_empty_permission_config_denies_everything` proves it.

`config/permissions.yaml` mirrors §11's shape:

```yaml
version: 1
agents:
  project_manager:
    github:
      list_recent_activity: allow      # read-only; the only grant that exists in M1
```

M1 contains no write or destructive operation, so `ASK_USER` is never returned (FR-121) — but the
value is in the enum, the column, and the decision function from day one, so M5 adds a queue and a
UI, not a new concept.

### 9.3 Tool framework (§10, §26.8, FR-100–105, ADR-000 Q1)

```python
@dataclass(frozen=True)
class ToolOperation:
    name: str
    params_model: type[BaseModel]      # argument schema — §26.8
    read_only: bool
    handler: Callable[[BaseModel], Awaitable[ToolResult]]

class ToolAdapter(Protocol):
    name: str
    operations: dict[str, ToolOperation]
```

`ToolManager.execute(tool, operation, params, meta: ExecutionMetadata)` — the order matters and
each step is a requirement:

0. **Runtime guard (A-3).** Reject the call unless it carries an `ExecutionMetadata` whose
   `validated_plan_id`, `request_id`, `task_id` and `agent_id` are all present; the plan object on
   the execution path is checked with `require_validated_plan()` at the same moment. A caller with
   no validated plan cannot reach step 1. All four fields are then written onto the `tool_calls`
   row, so every executed call names the plan that authorised it. (DC-14 later re-verifies that the
   stored `plans` row carries `validated = true`; see §6.1.)
1. **Resolve** tool + operation in the registry. Unknown → record `tool_calls` with
   `permission_decision=deny`, `status=not_executed`; return. (No adapter exists to call.)
2. **Agent grant precheck** — the agent's own `config/agents.yaml` tool list. FR-082 requires this
   rejection *before* the Tool Manager, so the agent runner checks it too; the duplicate check here
   is deliberate defence in depth against a future agent that forgets.
3. **Validate parameters** against `params_model` (Pydantic, `extra="forbid"`). On failure: record
   `tool_calls` with `permission_decision=deny`, `status=not_executed`, `error_kind=invalid_params`,
   **adapter not invoked** (FR-102, NFR-008). Recording a decision even here keeps FR-103's
   "non-null `permission_decision`" true for every row — an unparseable request is a denied request.
4. **Permission decision** (§9.2) → emit stage 9, write it to the row. FR-101/ET-4.
5. If not `ALLOW` → return without touching the adapter. (`ASK_USER` becomes a queue entry in M5.)
6. **Execute** the adapter inside `asyncio.timeout(op.timeout_s)`; catch every exception.
7. **Normalise** to `ToolResult{ok, data, error_kind, error_message}`. An adapter exception never
   propagates to the orchestrator (FR-104).
8. **Record** result, `duration_ms`; emit stage 10.

**The GitHub adapter (M1's one tool)**

- `GET https://api.github.com/repos/{owner}/{repo}/commits?per_page=20`,
  `.../pulls?state=open&per_page=20`, `.../issues?state=open&per_page=20` — three concurrent
  `httpx` GETs, 15 s timeout, `Authorization: Bearer <PAT>`, `Accept: application/vnd.github+json`,
  `X-GitHub-Api-Version: 2022-11-28`.
- Gotcha to encode, not to rediscover: **`/issues` returns pull requests too.** Filter out any item
  with a `pull_request` key or the PR count is double-counted.
- **`owner`/`repo` never come from the model.** The operation's parameter is `project_key`, validated
  against `config/projects.yaml`; the adapter looks the coordinates up. This closes the SSRF/
  wrong-repo class outright (threat A5) and satisfies ADR-000 Q7's "must be a config value".
- Rate limit: authenticated GitHub allows 5000 req/h; a turn uses 3. `x-ratelimit-remaining` is
  logged. A 403 with `x-ratelimit-remaining: 0` maps to `error_kind=rate_limited` →
  M1_CHAT_SPEC §5.7 copy.
- **Result projection is a security control, not tidiness** — see §9.4.

### 9.4 Prompt injection from tool output (§26.11/12, NFR-011/012) — the headline threat

An agentic system's distinctive vulnerability is that data returned by a tool is fed to a model that
also holds authority. Four controls, in decreasing order of strength:

1. **The analysis call — the only LLM request made after tool output exists — carries no `tools`
   parameter at all.** The model is given no callable tool, so no amount of injected text can cause
   one. The single tool invocation in an M1 turn is made by deterministic code from the
   already-validated plan. This is structural and it is the control that actually holds. (ADR-015
   removed the final-response call; that *reduces* this surface — there is now exactly one
   post-tool-output LLM request, not two.)
2. **The plan is produced before any tool output exists.** M1 does not re-plan, so tool content
   cannot influence which tool runs. *This advantage disappears in M6* when agents loop — recorded in
   the threat model as a deferred control with an owning milestone, so nobody inherits a false sense
   of safety.
3. **Field projection and length caps.** The adapter returns an allow-listed projection, never raw
   GitHub JSON: commits → `{sha[:7], message[:300], author_login, committed_at}`; PRs → `{number,
   title[:200], author_login, created_at, updated_at, draft}`; issues → `{number, title[:200],
   author_login, created_at, comments}`. **Issue and PR *bodies* are excluded entirely in M1** —
   free-form long text from strangers is the highest-yield injection surface and M1's summary does
   not need it.
4. **Delimiting and instruction.** Projected content is passed in a **user**-role message wrapped in
   `<untrusted_tool_result tool="github" operation="list_recent_activity"> … </untrusted_tool_result>`,
   with any occurrence of the delimiter inside the content escaped. The system prompt states that
   content inside that element is retrieved data which may contain text resembling instructions, that
   instructions inside it must never be followed, and that it can never change the task. This is the
   weakest of the four and is treated as such — it is defence in depth behind control 1.

**Controls 3 and 4 together are step 13 of the owner's M1 success test — "project/sanitise external
content before AI analysis" — and they are a required M1 control, not a deferred one.** Concretely,
in M1 that means: no GitHub response object is ever passed to a model; only
`tools/github/projection.py`'s allow-listed, length-capped, body-excluding output is, wrapped and
delimiter-escaped by the agent. The projection function is a security component and lives in the
security review's scope, with three named tests (`test_tool_result_projection_excludes_issue_bodies`,
`test_projection_escapes_the_untrusted_delimiter`,
`test_injected_instruction_in_commit_message_causes_no_action`).

**Gap, stated rather than hidden:** none of ET-1…ET-11 covers this step. It is covered by NFR-011/012
and by the three tests above, which is why they are mandatory in T19 and are not descopable. I have
recommended to the Delivery Manager that the SRS gain an **ET-12** for it so the milestone's own exit
criteria assert it.

NFR-011/012's test (a commit message reading "Ignore all previous instructions and…") passes because
of control 1, and would still pass with control 4 removed.

### 9.5 Trust-boundary walk — one real mutating request

Per my standing rule (memory L-001): before this architecture is issued, one **mutating** browser
request is traced across **every** trust boundary at real addresses and ports, and every mechanism it
needs is named in the config inventory (§14.4). L-001 now covers the provider and tool boundaries
too.

**Request: the owner types "Check on EasyClean Workforce" and presses Send.**

**TB1 · browser → API.**
Page is served by `next dev` at `http://localhost:3000`. The client generates
`request_id = crypto.randomUUID()` and calls:

```
POST http://localhost:8000/api/v1/chat
Origin: http://localhost:3000
Content-Type: application/json
X-SUNIL-Client: web
X-Request-Id: 3f1c…-4a
Cookie: sunil_session=…            (credentials: "include")
{"message":"Check on EasyClean Workforce","conversation_id":null}
```

- `Content-Type: application/json` and `X-SUNIL-Client` are both non-safelisted, so the browser first
  sends `OPTIONS /api/v1/chat` with `Access-Control-Request-Headers: content-type,x-sunil-client,x-request-id`.
- `CORSMiddleware(allow_origins=["http://localhost:3000"], allow_credentials=True,
  allow_methods=["GET","POST","OPTIONS"],
  allow_headers=["Content-Type","X-SUNIL-Client","X-Request-Id"], max_age=600)` answers it.
  **`allow_origins` must be an explicit list — with `allow_credentials=True` a wildcard is rejected
  by every browser.** That trap is the reason the origin is an env var (`WEB_ORIGIN`), not a literal.
- **The cookie reaches port 8000 because both servers are addressed as `localhost`.** Cookies ignore
  port, and `http://localhost:3000` → `http://localhost:8000` is *same-site* (same registrable host,
  same scheme) though *cross-origin*, so a `SameSite=Lax` cookie is sent.
  **Hard rule: never address one service as `127.0.0.1` and the other as `localhost`.** Those are
  different sites, `SameSite=Lax` then withholds the cookie on POST, and the failure looks like a
  broken login rather than a topology mistake. `scripts/dev-check.ps1` asserts both URLs use
  `localhost` and fails loudly if not. (This is precisely the class of gap L-001 exists to prevent.)
- **CSRF:** `X-SUNIL-Client` is required on every mutating request. A custom header cannot be sent
  cross-origin without a successful preflight, and the preflight only succeeds for `WEB_ORIGIN`. A
  cross-site attacker is additionally blocked by `SameSite=Lax` on POST. A page on another *localhost
  port* is same-site (so Lax does not help) but still fails the preflight — which is exactly why the
  header requirement exists rather than relying on SameSite alone. The dependency also rejects a
  request whose `Origin` header is present and not `WEB_ORIGIN`.

**Inside the API.** `CORSMiddleware` → `RequestContextMiddleware` (validate/accept `X-Request-Id`,
bind `request_id` to structlog contextvars, start the turn clock, create the `TraceBus` channel) →
`SessionMiddleware` (verify the signed cookie) → `require_owner_session` (401 if absent) →
`require_client_header` (403 if `X-SUNIL-Client` missing or `Origin` mismatched) → handler.
Request body validated by Pydantic (`message` 1…8000 chars).

**TB2 · API → Anthropic.** `AsyncAnthropic` over TLS to `https://api.anthropic.com`, outbound 443
only. API key from `Settings.anthropic_api_key: SecretStr`, injected at client construction; never in
a prompt. Per-call timeout from `config/models.yaml`; SDK retries disabled; SUNIL's retry wrapper
(3 attempts, 1/2/4 s, jitter) handles `ProviderTransientError`. Prompt and response are scrubbed
(§8.3) and written to `llm_calls`. Cost computed from the pinned price table.

**TB3 · orchestrator/agent → Tool Manager** (in-process privilege boundary). The agent may only name
tools listed in its own `config/agents.yaml` entry (FR-082); the Tool Manager re-checks, validates
parameters, calls the permission engine (default-deny), writes `tool_calls`, and only then reaches an
adapter (§9.3).

**TB4 · tool adapter → GitHub.** `httpx.AsyncClient` over TLS to `https://api.github.com`. PAT from
`Settings.github_token: SecretStr` in the `Authorization` header only. Repo coordinates from
`config/projects.yaml`, never from the model. Response is projected to an allow-list and capped
(§9.4) before it is allowed anywhere near a prompt.

**TB5 · app → database.** `sqlite+aiosqlite:///./var/sunil.db` in M1
(`postgresql+psycopg://…` when Postgres exists). The SQLite file holds conversation content and
prompts — `var/` is gitignored (§14.4) and the threat model records "no encryption at rest in M1" as
an accepted, dated risk.

**Return path.** HTTP 200:

```json
{"request_id":"3f1c…","conversation_id":"…","outcome":"ok",
 "message":{"id":"…","role":"assistant","content":"…","created_at":"…"},
 "task":{"id":"…","status":"completed","assigned_agent":"project_manager"},
 "trace":[{"stage":"message_received","offset_ms":0,"detail":{}}, …],
 "usage":{"input_tokens":4211,"output_tokens":388,"cost_usd":"0.012262"}}
```

**TB1 again · the SSE channel.** In parallel with the POST the client opened
`new EventSource("http://localhost:8000/api/v1/chat/3f1c…/events", {withCredentials: true})`.
That is a simple GET — `Accept: text/event-stream` is a safelisted header value, so there is **no
preflight**; it needs `Access-Control-Allow-Credentials: true` and an explicit origin, which the same
`CORSMiddleware` supplies. EventSource cannot set custom headers, so `X-SUNIL-Client` is not required
here — acceptable because the endpoint is read-only and CORS still governs who may read it. The
handler requires the session and matches the channel's owning `user_id`.

Every mechanism named above appears in the env inventory (§14.4): `WEB_ORIGIN`,
`NEXT_PUBLIC_API_BASE_URL`, `SESSION_SECRET`, `SESSION_COOKIE_NAME`, `ANTHROPIC_API_KEY`,
`GITHUB_TOKEN`, `DATABASE_URL`, `API_HOST`, `API_PORT`, `SUNIL_PROGRESS_EVENTS`.

### 9.6 Authentication (FR-007, ADR-000 Q3, ADR-007)

- `POST /api/v1/auth/login {username, password}`. Password verified with **stdlib
  `hashlib.scrypt`** (`n=2**14, r=8, p=1, dklen=32`, 16-byte random salt; stored as
  `scrypt$n$r$p$salt_b64$hash_b64`) and `hmac.compare_digest`. Verified working on this machine's
  Python 3.13. No `passlib`, no `bcrypt` — one less dependency and no version-skew bugs.
- Session = Starlette `SessionMiddleware` signed cookie (`itsdangerous`), `HttpOnly`, `SameSite=Lax`,
  `Path=/`, `max_age=86400`, name `sunil_session`, secret from `SESSION_SECRET`.
- Brute-force throttle: 5 consecutive failures → 60 s lockout, in-memory, keyed by username. Small,
  and Security will ask for it otherwise.
- The owner row is created by `scripts/seed-owner.py`, reading `OWNER_USERNAME` / `OWNER_PASSWORD`
  from the environment. No signup endpoint exists.
- Rejected: JWT in `localStorage` (XSS-readable, no revocation), OAuth/SSO (no IdP, absurd for one
  user), HTTP Basic (no logout, browser-controlled UI).

---

## 10. Agent framework and configuration

### 10.1 Runner

```python
@dataclass(frozen=True)
class AgentResult: summary: str; tool_calls: list[str]; ok: bool; error_kind: str | None

class Agent(Protocol):
    id: str
    async def run(self, plan: ValidatedPlan, task: Task, ctx: AgentContext) -> AgentResult: ...
```

`AgentContext` gives the agent exactly four capabilities and nothing else: `call_tool()` (routed
through the Tool Manager), `ask_model()` (routed through the Model Router), `memory` (its declared
scope only), `trace`. It holds no DB session, no HTTP client, no secrets — least privilege by
construction (§26.7, NFR-007).

`project_manager` in M1 (ADR-000 Q2): resolve `project_key` → call
`github.list_recent_activity` → ask the model for a 2–4 sentence summary highlighting anything that
looks like it needs attention → return. No planned-vs-actual reasoning; that is M6.

### 10.2 `config/agents.yaml`

```yaml
version: 1
agents:
  project_manager:
    role: "Manage software projects and identify risks."
    instructions:
      - "Review recent project activity."
      - "Highlight anything that looks like it needs attention."
      - "Never claim anything the tool result does not show."
    objectives: ["Report current project status."]
    memory_scope: [short_term]
    preferred_capability: general_reasoning
    escalation_capability: complex_reasoning
    tools:
      github: [list_recent_activity]
```

Changing role, instructions or tools requires no code change and no deployment (FR-084) — a restart
picks up the file. Startup cross-validates `agents.yaml` ↔ `permissions.yaml` ↔ `tools.yaml` and
refuses to boot on a mismatch.

---

## 11. API surface

### 11.1 Endpoints (M1)

| Method | Path | Purpose | Auth |
|---|---|---|---|
| POST | `/api/v1/auth/login` | `{username,password}` → sets session cookie | no |
| POST | `/api/v1/auth/logout` | clears session | yes |
| GET | `/api/v1/auth/session` | `{authenticated, user}` | no |
| POST | `/api/v1/chat` | **the turn** (FR-001/020/022) | yes + `X-SUNIL-Client` |
| GET | `/api/v1/chat/{request_id}/events` | SSE stage events | yes |
| GET | `/api/v1/trace/{request_id}` | full trace (debug, NFR-021 seed) | yes |
| GET | `/api/v1/health` | liveness + schema revision | no |

Versioned `/api/v1/` rather than §24's bare `/api/…` — a one-character forward-compatibility cost.
§24's other groups (`/tasks`, `/workflows`, `/agents`, `/approvals`, …) are reserved and arrive with
their milestones. WebSocket channels (§24) arrive with M2 streaming; M1's SSE is deliberately not a
WebSocket (ADR-009).

### 11.2 Copy ownership

**The API returns machine-readable enums and data; the web app owns every human-readable string.**
Failure kinds, trace stages and project keys cross the wire; labels and messages do not. This is why
`M1_CHAT_SPEC` can state "all copy in §5.6–5.9 is final, shippable text" and stay true — there is
exactly one place that text lives, and it is the frontend.

### 11.3 Turn outcomes

A processed turn returns **HTTP 200** with a discriminated `outcome`, even when the turn failed. The
HTTP transaction succeeded — it was authenticated, persisted and fully traced; conflating an agent
failure with a transport failure would lose the trace payload and give QA a worse assertion.

| `failure.kind` | Cause | Frontend (`ErrorCard variant`) |
|---|---|---|
| `provider_error` | retries exhausted (NFR-071), **or the §5.3 turn deadline was reached** (`error_kind = turn_deadline_exceeded`) | `generic` |
| `tool_failed` | adapter error / GitHub unreachable / rate-limited (FR-104) | `tool_failed` |
| `plan_rejected` | 3 plan attempts all failed validation (FR-062) | `plan_rejected` |
| `unknown_project` | plan returned `project_key: "__unknown__"` (FR-107, ET-11) | `unknown_project` |

`unknown_project` additionally returns `failure.known_projects: [{key, display_name}]` from
`config/projects.yaml`, so the Designer's requirement that the empty-state chips and the
unknown-project copy share one source of truth is satisfied by the API, not by two hard-coded lists.

Real HTTP errors are reserved for transport-level facts: 401 no session, 403 missing client header
or origin mismatch, 422 malformed body or malformed `X-Request-Id`, 429 login throttle, 500
unhandled defect.

### 11.4 Cancel — the Designer's escalation #2

**Decision: Cancel is client-side only in M1. The Designer's copy stands unchanged. ADR-010.**

The deciding reason is not effort, it is scope: a real server-side abort needs a terminal task state
that is neither `completed` nor `failed`, and FR-065's lifecycle — which QA is writing red tests
against right now — is exactly `pending → in_progress → completed|failed`. Adding `cancelled` three
days out means an SRS amendment and a re-write of tests that already exist. The cost of *not* having
it is one possibly-wasted turn's tokens (single-digit cents) and one orphaned read-only GitHub call.

The seam is built: `TraceContext.emit()` is already called at all twelve stage boundaries, so M2 adds
cooperative cancellation by checking a flag inside that one method plus a `cancelled` status — a
contained change, not a refactor. Recorded in §16 and in the threat model's deferred controls.

---

## 12. Frontend architecture

- **Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS 3.4.19**, pnpm, in `apps/web`.
  **Tailwind is pinned to v3.4** deliberately: `DESIGN_SYSTEM.md` ships a v3
  `tailwind.config.ts → theme.extend` block verbatim, and translating it to v4's CSS-first `@theme`
  on day one is an unforced token-drift risk. `create-next-app` now scaffolds v4, so the engineer
  must scaffold **without** Tailwind and add `tailwindcss@3.4.19 postcss autoprefixer` explicitly.
  Upgrade to v4 is M8 debt (§16). ADR-012.
- **A pure client application.** No server components fetching from the API, **no Server Actions, no
  Next.js route handlers proxying the API.** Reason: any of those would create a *second* trust
  boundary (browser→Next server) with its own cookie context and its own CSRF surface, for zero M1
  benefit. One boundary, walked in §9.5, is the whole point. `apps/web/src/app/(chat)/page.tsx` is
  `"use client"`.
- **Structure** (mirrors `M1_CHAT_SPEC.md` §7 one-for-one so the Designer's component names are the
  file names): `src/components/chat/{ChatShell,TopBar,MessageList,MessageBubble,AssistantMessage,
  TraceDisclosure,WorkIndicator,ErrorCard,Composer,SuggestionChips,JumpToBottomPill,StatusDot}.tsx`;
  `src/lib/{api.ts,phases.ts,copy.ts,useTurn.ts}`; `src/app/login/page.tsx`;
  `src/app/(chat)/page.tsx`.
- **`useTurn()`** is the one hook that owns a turn: generate `request_id`, open `EventSource`, POST
  with `AbortController`, map stage events → phase (`phases.ts`), enforce the 400 ms minimum phase
  display and the 20 s / 45 s thresholds, resolve to a message or an `ErrorCard` variant. Everything
  in `M1_CHAT_SPEC` §5.3 lives here.
- **Progressive enhancement:** if `EventSource` errors or `SUNIL_PROGRESS_EVENTS` is off, `useTurn`
  falls back to the Designer's deterministic client-side stepper. One hook, both variants — which is
  exactly what the Designer asked for in Assumption 1.
- **Streaming seam for M2:** `AssistantMessage`'s body is the single insertion point for token
  rendering (M1_CHAT_SPEC §5.4). No structural change needed.
- **Chrome-agnostic components**, per `DASHBOARD_DIRECTION.md` §2 — `ChatShell` supplies the
  full-viewport chrome, and nothing below it assumes a viewport.
- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` — the only backend coordinate the frontend knows.

---

## 13. Cost tracking and training-data capture

### 13.1 Cost

**(§29, FR-046, NFR-030, ET-9.)** Every **provider attempt** — not every logical stage (A-2) —
writes an `llm_calls` row with provider, model, capability, purpose, `attempt`, input/output tokens,
`cost_micro_usd`, `pricing_version`, `latency_ms`, `error_kind`, and the linking
`request_id`/`task_id`/`agent_id`. Cost = `(in/1e6·in_price + out/1e6·out_price)` from the pinned
table in `config/models.yaml`, rounded to micro-USD. A turn's cost is the **sum over its attempts**,
which is the only definition that stays true when a retry happens; a failed attempt that consumed
input tokens still costs money and still appears. Aggregation views are M3 (NFR-031); the **write
path exists from M1**, which is the requirement.

### 13.2 Training-data capture policy (A-6, ADR-014)

**(§30, NFR-050.)** The tables already written *are* the capture: `messages` (original request,
final result), `audit_events` (context loaded, memory retrieved), `plans` (every attempt, accepted
and rejected), `llm_calls` (full prompts and responses, redacted), `tool_calls` (parameters and
results), `task_status_events` (outcome). `GET /api/v1/trace/{id}` reassembles a complete trace from
them, which is both the NFR-050 verification query and the export shape V3 will consume. `approvals`
adds user corrections from M5 (NFR-051).

**Secret redaction is not a capture policy.** §8.3 removes credentials. It does not, and cannot,
decide whether a client's support conversation, a private repository's contents or a piece of
personal information belongs in a corpus that a model will be fine-tuned on in V3. Those records
contain no API key and are still not training data. So capture is governed by an explicit,
recorded policy from V1 — because the context needed to classify a record (who asked, which project,
which tool, which agent) exists **only at capture time**, and reconstructing it in V3 from stored
rows would be guesswork applied to data that has already been persisted under no policy at all.

**The four policy values, and what each one actually does in M1:**

| Policy | Stored | Enforced in M1? |
|---|---|---|
| `none` | nothing but the row's existence, ids and timestamps — content columns written `NULL` | **Yes.** The writer nulls the content columns |
| `metadata_only` | ids, timestamps, counts, lengths, token usage, cost, `error_kind` — **no content** | **Yes.** Same writer path |
| `redacted_full` | full content after §8.3 redaction. **The M1 default** | **Yes** (it is today's behaviour) |
| `full_local_only` | full redacted content, flagged as never-exportable and never-uploadable | **Recorded, not enforced.** M1 has one machine and no export path, so there is nothing yet to prevent; enforcement is a V2/V3 control on the export and training pipelines. Stated here so nobody reads the value as a working guarantee |

**Resolution** is one pure function, called by the persistence layer, never by an agent:

```python
def resolve_capture(*, kind: CaptureKind, project_key: str | None,
                    agent_id: str | None, source: ContentSource) -> CaptureDecision
# → CaptureDecision(capture_policy, sensitivity, retention_class, training_eligible)
```

Defaults come from `config/capture.yaml` (a sixth registry file, cross-validated at startup like the
others), keyed by content kind, with a per-project override — so `projects.yaml` can mark one
client's project `confidential / metadata_only` without a code change. M1 ships exactly one project
and the defaults below.

`training_eligible` is **derived, never hand-set**:
`training_eligible = capture_policy in {redacted_full, full_local_only} and sensitivity in {public, internal}`.
`full_local_only` may still be training-eligible — it constrains *where* training may happen (on
this machine, V3), not *whether*.

**M1 defaults, stated so the exit run's data is interpretable:**

| Content | policy | sensitivity | retention | training_eligible |
|---|---|---|---|---|
| Owner's chat message / assistant reply | `redacted_full` | `internal` | `standard` | true |
| Plan JSON (accepted and rejected) | `redacted_full` | `internal` | `standard` | true |
| LLM prompt/response (`llm_calls`) | `redacted_full` | `internal` | `standard` | true |
| GitHub projection in `tool_calls.result` (commit titles, PR/issue titles) | `redacted_full` | `internal` | `standard` | true |
| Any secret or credential | — | — | — | **never stored at all** (§8.3, ET-10) |
| Payment/card data | — | — | — | **never stored at all**; no code path handles it in V1 |
| Short-term memory rows | `redacted_full` | `internal` | `transient` | true |

**What is schema-only in M1, said plainly:** `retention_class` is written and nothing purges — there
is no retention job until M11 (debt D-11). `training_eligible` is written and nothing exports —
there is no corpus builder until V3. `full_local_only` is written and nothing restricts. What is
*real* in M1 is that `none` and `metadata_only` genuinely null the content columns, that the four
values are decided at capture time by one auditable function, and that the columns exist so V3
inherits classified data rather than an undifferentiated pile.

---

## 14. Local development topology

### 14.1 What a developer runs **today**, with no Docker

This is the path that matters. **M1 needs neither Postgres nor Redis** (ADR-001, ADR-005, ADR-013),
so the build lane does not wait for anyone, and this is still the primary path.

*Updated 2026-08-14: Docker Desktop is now running (server 29.7.2, Linux containers, Compose v5.3.1).
That changes nothing here by design — the three ADRs above were taken so that a stopped daemon could
never block M1, and the same reasoning says a started daemon should not now pull containers onto the
critical path four days from the milestone. Docker's availability makes the compose stack (T17) a
convenience and makes D-2's PostgreSQL verification possible before Gate 3; it does not make either
one an M1 dependency. `docs/ENVIRONMENT.md` still records the daemon as down and is now stale on that
point — the DevOps lane owns that document.*

```powershell
# backend  — terminal 1
cd C:\repo\SUNIL\apps\api
python -m venv .venv                       # note: `python`, never `python3` (broken Store stub)
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
copy ..\..\.env.example ..\..\.env         # then fill in the two secrets
alembic upgrade head                       # creates var\sunil.db
uvicorn sunil.main:app --host 127.0.0.1 --port 8000 --reload

# frontend — terminal 2
cd C:\repo\SUNIL\apps\web
pnpm install
pnpm dev                                   # http://localhost:3000

# preflight — terminal 3
pwsh scripts\dev-check.ps1                 # asserts health, origins, and localhost-vs-127.0.0.1
```

Ports: API **8000**, web **3000**. **4317 is the Minions Portal and must never be bound.**
5432/6379 stay free until Docker comes up.

`--host 127.0.0.1` with a browser origin of `http://localhost:8000` is the one place this topology
can bite on Windows, because `localhost` may resolve to `::1` first. Browsers fall back to
`127.0.0.1`, but `scripts/dev-check.ps1` probes `http://localhost:8000/api/v1/health` explicitly and,
if it fails, prints the one-line remedy: rerun uvicorn with `--host localhost`.

### 14.2 The compose stack, for when the daemon is up

`infra/docker/docker-compose.yml` — authored and committed in M1, used the moment Docker Desktop is
started, not before:

| Service | Image | Ports | Volume | Profile |
|---|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg17` | `5432:5432` | `sunil_pgdata:/var/lib/postgresql/data` | default |
| `redis` | `redis:7-alpine` | `6379:6379` | `sunil_redisdata:/data` | `queue` (not started by default) |
| `api` | built from `infra/docker/Dockerfile.api` | `8000:8000` | source bind-mount for reload **plus `./config:/app/config:ro`** (§14.5) | `full` |

`pgvector/pgvector:pg17` rather than plain `postgres` so M7's extension is a `CREATE EXTENSION`, not
an image migration. Redis sits behind a profile because **nothing in M1 or M2 uses it**; it is there
for M10's scheduler. Switching the app to Postgres is one env var:
`DATABASE_URL=postgresql+psycopg://sunil:sunil@localhost:5432/sunil` then `alembic upgrade head`.

### 14.3 Dependencies — every one checked to exist for Python 3.13 / Node 24 on 2026-08-14

Backend: `fastapi` 0.141.1 · `uvicorn` 0.52.3 · `pydantic` 2.13.4 · `pydantic-settings` 2.15.0 ·
`sqlalchemy` 2.0.52 · `alembic` 1.19.1 · `aiosqlite` 0.22.1 · `psycopg[binary]` 3.3.4 ·
`greenlet` 3.5.5 · `anthropic` 0.122.0 · `httpx` 0.28.1 · `structlog` 26.1.0 · `itsdangerous` 2.2.0 ·
`pyyaml` 6.0.3. Dev: `pytest` 9.1.1 · `pytest-asyncio` 1.4.0 · `ruff`.
Password hashing uses **stdlib `hashlib.scrypt`** — verified working on this interpreter; no
`passlib`, no `bcrypt`.
Frontend: `next` 16.3.1 · `react` 19.2.8 · `tailwindcss` **3.4.19** (pinned, §12) · `typescript`.

No LangChain, no LiteLLM, no Celery, no Redis client, no `sse-starlette`. SSE is ~40 lines of
`StreamingResponse` and a dependency avoided three days from a deadline is a risk avoided (ADR-003,
ADR-005, ADR-009).

### 14.4 Environment inventory (`.env.example`, placeholders only)

| Variable | Example | Used by | Secret |
|---|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./var/sunil.db` | db/session | contains one when Postgres |
| `ANTHROPIC_API_KEY` | `sk-ant-REPLACE_ME` | providers/anthropic | **yes** |
| `GITHUB_TOKEN` | `github_pat_REPLACE_ME` | tools/github | **yes** |
| `SESSION_SECRET` | `REPLACE_ME_32_BYTES` | SessionMiddleware | **yes** |
| `SESSION_COOKIE_NAME` | `sunil_session` | SessionMiddleware | no |
| `WEB_ORIGIN` | `http://localhost:3000` | CORS + origin check | no |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | uvicorn | no |
| `LOG_LEVEL` | `INFO` | logging | no |
| `SUNIL_PROGRESS_EVENTS` | `false` | SSE feature flag; **defaults false until T12 lands** (§8.4) | no |
| `SUNIL_CONFIG_DIR` | `./config` | registry loaders (§14.5) | no |
| `SUNIL_TURN_DEADLINE_S` | `40` | orchestrator turn deadline (§5.3) | no |
| `OWNER_USERNAME` / `OWNER_PASSWORD` | `isuru` / `REPLACE_ME` | seed script only | **yes** |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | `apps/web` | no |

Also gitignore: `var/` (the SQLite database and any local artefacts). `.env` is already ignored.

### 14.5 Config deployment policy (A-7, ADR-016)

§2.2 says "config is not code" and FR-084 requires agent role, instructions and permissions to
change **without a code deployment**. That sentence is only true if the deployment mechanism keeps
the config outside the artefact. Bake `config/*.yaml` into a Docker image and every permission edit
becomes an image build — the requirement would be satisfied on paper and false in practice.

**V1 policy:**

1. **`config/` is never `COPY`ed into an image.** `Dockerfile.api` copies the package and nothing
   from `config/`. Compose mounts `./config:/app/config:ro` (read-only: the API reads config, it
   never writes it). A hosted deployment mounts the same directory from a volume, a config map or a
   secrets-manager-rendered file — the mechanism is the deployment's business; *not in the image* is
   the rule.
2. **`SUNIL_CONFIG_DIR` names the directory**, defaulting to `./config`. There is exactly one place
   the loaders look, and it is an environment variable, so an operator can relocate config without
   touching code.
3. **A config change takes effect on restart.** No hot reload, no file watcher, no SIGHUP in V1: the
   registries are cross-validated once at startup and refusing to boot on a mismatch is the control
   that makes a bad edit loud (§10.2). Reloading mid-flight would let a turn straddle two permission
   sets, which is precisely the ambiguity the permission engine exists to remove. Restart-on-change
   is explicitly sufficient for local development and for V1's single-instance deployment.
4. **"No code deployment" is not "no change control."** `config/permissions.yaml` *is* a privilege
   boundary and `config/projects.yaml` *is* the tool's target list; both are in git, both are
   reviewed like code, and DC-11 (permission-config change auditing, M5) exists because a
   deployment-free change is exactly the kind that escapes an audit trail.

---

## 15. Gate 2 — decided, and what is still outstanding

**The owner reviewed this architecture on 2026-08-14 and approved the direction after the targeted
corrections now applied as A-1…A-9.** Items 1, 3 and 4 below are therefore settled; item 5 is
settled by Docker Desktop now running (server 29.7.2, Linux containers, Compose v5.3.1 — verified),
which makes the no-Docker path a *contingency* rather than the primary plan, without moving Docker
onto M1's critical path. **Item 2 is the one thing still outstanding and it blocks the exit run.**

1. ~~**Approve the architecture and ADR-001…013**~~ — **done.** SQLite-for-M1 with Postgres as the V1
   target (ADR-001), no Redis in M1 (ADR-005), no pgvector until M7 (ADR-013) are accepted, along
   with the single `sunil` package, SSE over WebSocket, YAML agent config and `/api/v1` versioning.
2. **⏳ Supply two secrets** (into `.env`, never into the repo):
   `ANTHROPIC_API_KEY`, and a **fine-grained GitHub PAT** scoped to
   `codely-isuru/easy_clean_workforce` with **Contents: read** + **Pull requests: read** +
   **Issues: read** and nothing else.
3. ~~**Confirm the SSE progress channel is in scope**~~ — **decided, and downgraded.** ADR-009 stands,
   but the owner's review pre-classifies **T12 (SSE) as OPTIONAL / post-M1**. The frontend's fallback
   stepper carries the UI if it is not built.
4. ~~**Accept client-side-only Cancel for M1**~~ — **done** (ADR-010).
5. ~~**Start Docker Desktop**~~ — **done.** Still not on M1's critical path (ADR-001/005/013), and
   still needed before Gate 3 so the Alembic migration is verified once against real PostgreSQL
   (§16, D-2).

---

## 16. Deviations from the plan of record, and the debt register

All deviations in one place, as is my standing convention.

| # | Deviation from `ROADMAP.md` | Argued in |
|---|---|---|
| V-1 | §20's top-level `core/ providers/ agents/ tools/` become subpackages of one installable `sunil` package | §2.1, ADR-011 |
| V-2 | `core/models/` → `core/routing/`; `core/agents/` → `core/agent_framework/`; `core/tools/` → `core/tool_framework/` | §2.1 |
| V-3 | Backend tests at `apps/api/tests/`, not top-level `tests/` | §2.1 |
| V-4 | §4/§14 Epic 1 name PostgreSQL as V1 foundation; M1 defaults to SQLite | §7.1, ADR-001 |
| V-5 | §4/§14 Epic 1/§23 Step 1 name Redis; M1 and M2 use none | §14.2, ADR-005 |
| V-6 | §4/§13 name pgvector; no vector column exists until M7 | §7.5, ADR-013 |
| V-7 | §21's `Agent` is config, not a table | §7.3 |
| V-8 | §24's API paths gain a `/v1` segment | §11.1 |
| V-9 | M1 progress uses SSE, not §24's `/ws/…` WebSocket channels | §8.4, ADR-009 |
| V-10 | M1 runs **two** logical LLM stages, not the three §22 implies; the final response is composed deterministically from the agent's summary | §1.1, §5, ADR-015 |
| V-11 | A sixth registry file, `config/capture.yaml`, joins the five in §20 | §13.2, ADR-014 |

**Checked against §33's twelve non-negotiable rules: no contradiction.** Rules 2, 3, 5, 10, 11 and 12
are the ones this architecture spends its effort on (§1.1, §6, §8, §9). Rule 6 ("sensitive actions
require explicit approval") is *not exercised* in M1 because M1 has no sensitive action (ADR-000 Q4) —
the decision point, the enum and the column all exist; only the human-in-the-loop UI is deferred to
M5, which is a scope decision the owner already made, not an architectural contradiction. No ADR
arguing against a §33 rule is therefore required.

**Debt register** — every one of these is a knowing trade of depth for the 2026-08-18 date:

| ID | Debt | Owed by |
|---|---|---|
| D-1 | Single uvicorn worker required by the in-process `TraceBus`; multi-worker needs Redis pub/sub | M10 |
| D-2 | Alembic migration verified on SQLite only; must be run once against real PostgreSQL | before Gate 3 |
| D-3 | Signed-cookie session cannot be revoked server-side; a session table would fix it | M5 |
| D-4 | Cancel is client-side only; cooperative abort + a `cancelled` task state | M2 |
| D-5 | Tailwind pinned to 3.4.19; migrate the token contract to v4 `@theme` | M8 |
| D-6 | **Amended (A-8):** M1 ships validation CI (`ruff`, `pytest`, frontend typecheck + build, security boundary tests) as a merge gate — task T21. **Deployment** CI, dependency CVE scanning and secret scanning remain deferred (FR-009) | M11 |
| D-7 | SQLite file unencrypted at rest and holds conversation content | M11 |
| D-8 | Prompt-injection safety in M1 leans on "no re-planning"; M6's agent loop invalidates that | M6 |
| D-9 | No aggregate cost reporting, only per-call rows (NFR-031) | M3 |
| D-10 | Capability metadata is a static table; the Models API (`client.models.list()`) is the real source | M3 |
| D-11 | `retention_class` is captured but nothing purges; no retention job exists (ADR-014) | M11 |
| D-12 | NFR-060 is reported in M1 as median/max over a handful of timed runs, not a measured p95 (§5.2) | M11 |
| D-13 | `full_local_only` is recorded but unenforced — there is no export or training path to restrict yet (ADR-014) | V3 |
| D-14 | The final-response synthesiser is deferred; M6's multiple concurrent agent results will need one (ADR-015) | M6 |

---

*Companion documents:* [`docs/decisions/`](decisions/) (ADR-001…013) · [`docs/THREAT_MODEL.md`](THREAT_MODEL.md) · [`docs/M1_BUILD_PLAN.md`](M1_BUILD_PLAN.md)
