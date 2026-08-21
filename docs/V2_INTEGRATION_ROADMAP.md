# SUNIL V2 — Integration Roadmap (finalised, n8n edition)

**Status:** PROPOSAL on branch `V2` — not plan-of-record until the owner merges.
**Relationship to plan of record:** extends [`ROADMAP.md`](ROADMAP.md); does **not** supersede it. The live M1 core (orchestrator, permission engine, plan validation, trace spine — verified 2026-08-19) is kept and remains the control plane. In-flight M2 (streaming) and M9 (voice) continue unchanged.
**Decision record:** [`decisions/ADR-030-integrate-open-source-components.md`](decisions/ADR-030-integrate-open-source-components.md) · **Build plan:** [`V2_DEVELOPMENT_PLAN.md`](V2_DEVELOPMENT_PLAN.md) · **Diagram:** [`design/ARCHITECTURE_V2_FINAL.html`](design/ARCHITECTURE_V2_FINAL.html)

> **Finalised 2026-08-21.** Supersedes the earlier Windmill-edition draft: **n8n** is the
> workflow/scheduler and connector fabric, and **OmniRoute** is admitted as a dev-only lane.

---

## 1. Principle

M1 proved the control plane: deterministic orchestration, validated plans, per-operation permissions, full audit. The remaining V1 epics (tools breadth, memory, scheduler, remaining agents, local models) are mostly **commodity engineering** now solved by mature open-source projects. V2 integrates them behind SUNIL's existing seams instead of hand-building each one.

SUNIL stays the product: the orchestrator, permission engine, audit spine, dashboard and entity memory are ours. Integrated components are replaceable vendors behind our interfaces — the same rule the roadmap already applies to LLM providers.

All components verified from source/GitHub on 2026-08-19 (see ADR-030 for licences, maturity and alternatives considered).

## 2. What gets integrated, and where it plugs in

| Component | Licence | Plugs into (existing seam) | Replaces (from-scratch work) |
|---|---|---|---|
| **MCP client + official MCP servers** (GitHub, Gmail, Calendar, Jira, Stripe, filesystem, terminal) | varies, official | `core/tool_framework` — new `MCPToolAdapter` beside the native GitHub tool; permission matrix maps agent × server × tool exactly as today | ~10 hand-written tool adapters (Epic 7) |
| **LiteLLM** (proxy) | MIT · 54k★ | behind `core/routing` — Model Router keeps capability/privacy policy; LiteLLM handles provider fan-out, retries, virtual key per agent, budgets | provider adapters ×N, cost plumbing (Epic 3 remainder, §29) |
| **Mem0** (pgvector backend) | Apache-2.0 · 63k★ | behind `core/memory` manager interface; same Postgres | embedding/retrieval engine (Epic 9 core) — entity schema stays ours |
| **OpenHands** | MIT · 84k★ | new `agents/developer` that delegates to OpenHands over its API; git writes stay approval-gated (`merge_main: ask_user`) | Developer + QA agent internals (Epic 5 part) |
| **n8n** (workflows + connector fabric) | Sustainable Use (internal) | triggers call `POST /api/v1/chat`; n8n **MCP Server** exposes workflows as governed tools via the MCP adapter | Scheduler + autonomous workflow engine (Epic 12) **and** long-tail connectors (WordPress/WooCommerce/SharePoint/client APIs) |
| **Hermes Agent** | MIT | optional channel gateway: Telegram/WhatsApp/Signal → SUNIL conversation API (SUNIL remains the brain; Hermes surfaces only) | messaging-channel layer (V2 nice-to-have) |
| **Langfuse** | MIT core · 32k★ | subscriber on the existing trace spine / LiteLLM callback | LLM analytics + evals UI (§27–28 extensions) — audit_events remain source of truth |
| **Ollama / vLLM** local Qwen | — | one more LiteLLM provider; Model Router privacy rules route LOCAL-ONLY | local provider adapter (V2 Epic 1) |
| **OmniRoute** (dev lane only) | MIT | one more LiteLLM provider, **PUBLIC workloads only**, dev/experimentation | — (fenced; never client/production data) |

Explicitly **kept custom** (the product): orchestrator + plan validation, permission engine + approvals, audit spine, Next.js dashboard, entity schema, Codely Support tool, privacy classifier.

## 3. Phases

Sequenced to not collide with in-flight M2/M9. Each phase = PRs to `main` (via the `V2` line), STATUS.md updated per merge, exit evidence required. The concrete parallel-stream execution is in [`V2_DEVELOPMENT_PLAN.md`](V2_DEVELOPMENT_PLAN.md); the phase labels below map to it.

### Phase V2-A — MCP tool expansion (first; highest leverage)
- [ ] `MCPToolAdapter` in `core/tool_framework` (stdio + streamable HTTP)
- [ ] Official GitHub MCP server mounted beside the native tool; parity test
- [ ] Gmail, Google Calendar, Jira, Stripe MCP servers wired; permission matrix entries per operation (`email.send: ask_user`, `stripe.refund: ask_user`, `database.delete: deny`)
- [ ] **n8n MCP Server** mounted through the same adapter; its workflow-tools get permission entries
- [ ] Prompt-injection posture: MCP results treated as untrusted input (ROADMAP §26.11)

**Exit:** PM agent reads Jira + GitHub through MCP in one governed turn; a write op parks as ASK_USER; audit shows adapter type per call.

### Phase V2-B — Model gateway consolidation
- [ ] LiteLLM deployed (Compose); Claude/OpenAI/Codex behind it; virtual key per agent with budgets
- [ ] `core/routing` targets LiteLLM; capability/privacy policy unchanged; provider keys leave app env
- [ ] OmniRoute registered as a dev-lane provider (PUBLIC workloads only)
- [ ] Optional: Langfuse subscriber for cost/evals views

**Exit:** all `llm_calls` audit rows show gateway path; per-agent spend visible; kill-switch fallback to direct provider documented.

### Phase V2-C — Memory V1 via Mem0
- [ ] SQLite → Postgres migration (schema already portable per ADR-001); pgvector enabled
- [ ] Mem0 on existing Postgres/pgvector behind `core/memory`
- [ ] Entity schema (clients, projects, people) + linkage to memories — custom
- [ ] Retrieval wired into orchestrator context loading; write rules per ROADMAP §13

**Exit:** "what did we agree with client X?" answered from memory with sources; memory writes audited.

### Phase V2-D — Developer/QA agents via OpenHands
- [ ] OpenHands sandboxed (Docker); `agents/developer` delegates tasks to it
- [ ] Git policy: `push_branch: allow`, `merge_main: ask_user`; PM → Developer handoff

**Exit:** "fix this bug and raise a PR" lands a PR with approval-gated merge, fully traced.

### Phase V2-E — Scheduled workflows via n8n
- [ ] Morning Codely brief, project monitor, support sweep as n8n flows calling the SUNIL chat API
- [ ] App-event triggers (ticket, email, Stripe event) → governed turns

**Exit:** one week unattended, exceptions notified, zero unaudited actions.

### Phase V2-F — Channels via Hermes (optional)
- [ ] Hermes gateway bridges Telegram/WhatsApp → conversation API; no tools/credentials in Hermes

**Exit:** governed turn from Telegram with identical audit trail.

### Phase V2-G — Local model
- [ ] Qwen via Ollama (start) / vLLM (scale) behind LiteLLM; privacy classifier routes LOCAL-ONLY
- [ ] Shadow-mode comparisons recorded (§16 Epic 4)

**Exit:** V2 acceptance test (ROADMAP §17) passes.

## 4. Risks
- MCP servers vary in quality — pin versions, contract-test each mounted server.
- LiteLLM becomes a single point of failure — HA or documented direct-provider fallback.
- n8n Sustainable Use Licence: internal use only, no resale as a hosted service. Ops: route `/mcp*` to a single webhook replica when scaling; disable reverse-proxy buffering for SSE.
- Langfuse adds ClickHouse if adopted.
- OpenHands is beta — sandbox strictly, approvals on all git writes.
- OmniRoute fenced to the dev lane and PUBLIC workloads; never client/production data.
- Scope guard: this proposal adds no new product surface; it swaps build-vs-integrate on already-planned epics.
