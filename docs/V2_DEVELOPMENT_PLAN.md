# SUNIL V2 — Development Plan (parallel streams, plug-in integration)

**Date:** 2026-08-19, finalised 2026-08-21 · **Basis:** finalised architecture (ADR-030, n8n edition) · **Repo:** codely-isuru/SUNIL · **Branch:** `V2`
**Design rule:** every stream builds against a frozen contract, not against another stream's code — so streams run simultaneously and plug in at the end. This mirrors how the repo already works (ADR-017 base-URL test seams, exclusive file ownership per task).
**Companion docs:** [`decisions/ADR-030-integrate-open-source-components.md`](decisions/ADR-030-integrate-open-source-components.md) · [`V2_INTEGRATION_ROADMAP.md`](V2_INTEGRATION_ROADMAP.md) · [`design/ARCHITECTURE_V2_FINAL.html`](design/ARCHITECTURE_V2_FINAL.html). **Status:** proposal on `V2` — not plan-of-record until the owner merges; M1 stays the live control plane, M2/M9 untouched.

---

## Phase 0 — Contracts & platform (1 week, everyone together, blocks everything)

Freeze the five seams so parallel work can't drift:

| Contract | Where | Consumers |
|---|---|---|
| C1 — Tool adapter interface | `core/tool_framework` (exists; document + version it) | Stream A, E |
| C2 — Provider base-URL override | `core/routing` settings (exists per ADR-017) | Stream B |
| C3 — Memory provider interface | `core/memory` (define: `recall(query, scope)`, `write(item, rules)`) | Stream C |
| C4 — Approval API | `POST /api/v1/approvals` + decision webhook (define OpenAPI now) | Stream D, A |
| C5 — Turn-trigger API | existing `POST /api/v1/chat` (already stable) | Stream E, F |

Platform tasks: Docker Compose adds Postgres+pgvector, LiteLLM, n8n containers alongside api/web; `.env.example` updated; contract tests (FakeProvider-style fakes) published for C1–C4 so every stream tests against fakes, not each other.

**Exit:** contracts merged to `main` as interfaces + fakes + OpenAPI; Compose stack boots green.

---

## Phase 1 — Six parallel streams (weeks 2–5)

Each stream is independently mergeable behind a feature flag; none touches another stream's files. M2/M9 (in-flight) own their files — no stream below touches streaming or speech modules.

### Stream A — MCP tools (backend dev 1)
`MCPToolAdapter` implementing C1 (stdio + streamable HTTP) → mount official GitHub MCP beside the native tool (parity test) → Gmail, Calendar, Jira, Stripe servers → permission matrix entries per operation → results treated as untrusted input (§26.11).
**Exit:** PM agent reads GitHub+Jira via MCP in one governed turn; a write op parks via C4 fake.

### Stream B — Model gateway (backend dev 2, small — pairs with Stream C owner)
LiteLLM container, providers behind it, virtual key per agent with budgets; `core/routing` pointed via C2 settings (no code change to router policy); rollback = flip base URL back.
**Exit:** all `llm_calls` rows show gateway path; per-agent spend queryable; direct-provider fallback documented.

### Stream C — Memory & entities (backend dev 2)
SQLite→Postgres migration (schema already portable per ADR-001) → pgvector → Mem0 behind C3 → entity schema (clients, projects, people) + linkage → orchestrator context loading uses `recall()`.
**Exit:** "what did we agree with client X?" answered with sources; memory writes audited.

### Stream D — Approvals & ops dashboard (frontend dev + backend support)
Approvals service implementing C4 (park → notify → decide → resume/refuse) → dashboard pages: approvals queue, agent activity, tasks, projects, audit browser (reads audit_events) → owner auth reused.
**Exit:** approve a parked (fake) call from the UI and watch it resume; reject → agent receives refusal.

### Stream E — n8n workflows (you / automation-savvy dev)
n8n container → trigger workflows calling C5 (morning brief, project monitor, support sweep) → MCP Server Trigger workflows exposing WordPress/WooCommerce/SharePoint/client-API actions as tools (consumed later via Stream A's adapter; until then, tested with any MCP client) → credentials in n8n vault only.
**Exit:** scheduled brief lands as a governed turn; one n8n workflow callable as an MCP tool.

### Stream F — OpenHands dev agent (backend dev 3 or deferred)
OpenHands sandboxed in Docker → `agents/developer` delegates via its API → git policy: `push_branch: allow`, `merge_main: ask_user` (through C4).
**Exit:** "fix bug X, raise a PR" produces a PR; merge waits for approval.

---

## Phase 2 — Plug & integrate (weeks 6–7, whole team)

Order of plugging (each step replaces a fake with the real thing):

1. A + B: MCP tool turns run through LiteLLM (traces show both chokepoints).
2. A + E: n8n's MCP server mounted in the adapter; its tools get permission entries.
3. A/E/F + D: real ASK_USER calls flow into the approvals UI (replace C4 fake).
4. C in: orchestrator context loading switches from stub to Mem0/entities.
5. E triggers on: scheduled workflows run against the fully wired system.

**Exit (V1 acceptance, ROADMAP §15):** "SUNIL, check everything happening at Codely today and tell me what requires my attention" — plan → agents → MCP reads → analysis → summary → approval request for anything sensitive → memory write → complete audit chain.

---

## Phase 3 — Hardening (week 8)

Security review (credential audit: nothing in agent env; least privilege per agent; prompt-injection tests on MCP/n8n results) · failure/retry drills (LiteLLM down → fallback; n8n down → tools degrade gracefully) · backup/restore drill (Postgres, n8n vault) · load/latency baseline · evals baseline (optional Langfuse) · docs + STATUS updates.

**Exit:** one week of scheduled workflows unattended, zero unaudited actions.

---

## Phase 4 — Later (sequenced, not parallel)

- **V2-G local model:** Qwen via Ollama→vLLM behind LiteLLM; privacy classifier enforces LOCAL-ONLY; shadow-mode cloud-vs-local comparisons. Needs GPU hardware decision first.
- **V2-F Hermes channels (optional):** Telegram/WhatsApp → conversation API.
- **V3:** dataset from ADR-014 captures → LoRA fine-tune → serve behind LiteLLM.

---

## Coordination rules

1. Nothing merges without its contract tests passing against the fakes.
2. Feature flags per stream; `main` stays releasable.
3. Exclusive file ownership per stream (as M9 build plan does); M2/M9 files untouchable.
4. Every PR updates STATUS.md; every phase exit records evidence.
5. Weekly integration checkpoint from week 3: boot the full Compose stack, run cross-stream smoke tests early.

## Suggested staffing (minimum viable: 2 devs + you)

- Dev 1: Stream A → integration lead
- Dev 2: Streams B+C → hardening lead
- You: Stream E + owner approvals + architecture rulings
- Dev 3 / stretch: Streams D, F (or D to frontend contractor; F deferred to Phase 4)

With 3 devs + you: ~8 weeks to V1-feature-complete. With 2 devs + you: defer F, fold D's dashboard scope to approvals-only ≈ 9–10 weeks.
