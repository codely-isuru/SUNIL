# ADR-030 — Integrate open-source components for remaining V1/V2 epics (n8n edition)

**Status:** Proposed (branch `V2`) · **Date:** 2026-08-19, finalised 2026-08-21 · **Owner decision pending**

> This is the **finalised** ADR-030. It supersedes the earlier `update/v2-architecture`
> draft (Windmill edition) in two ways: **n8n replaces Windmill** as the workflow/scheduler
> and connector fabric, and **OmniRoute** is admitted as a dev-only experimentation lane
> behind LiteLLM. Companion documents: [`../V2_INTEGRATION_ROADMAP.md`](../V2_INTEGRATION_ROADMAP.md)
> and [`../V2_DEVELOPMENT_PLAN.md`](../V2_DEVELOPMENT_PLAN.md). Architecture diagram:
> [`../design/ARCHITECTURE_V2_FINAL.html`](../design/ARCHITECTURE_V2_FINAL.html).

## Context

M1 is complete and live-verified: deterministic orchestrator, validated plans, permission
engine, GitHub tool, trace spine, PM agent (564 tests; live turn 2026-08-19). The remaining
epics — tool breadth, memory, scheduler, developer/QA agents, channels, local models — were
planned as from-scratch builds. An evaluation of the 2026 open-source landscape (all repos
verified from source on 2026-08-19) found mature, licence-compatible components covering most
of that scope. A full evaluation of Hermes Agent (NousResearch) as a wholesale replacement for
SUNIL was also performed and rejected.

**The governing principle is unchanged:** SUNIL is the product. The orchestrator, plan
validation, permission engine, audit spine, dashboard and entity memory schema stay custom.
Every integrated component is a replaceable vendor behind a SUNIL-owned seam — the same rule
the roadmap already applies to LLM providers. Nothing here retires live M1 code; each
integration plugs in behind an interface that already exists.

## Decision

Integrate, behind existing SUNIL seams, rather than build:

1. **MCP client in `core/tool_framework`** + official MCP servers (GitHub, Gmail, Calendar,
   Jira, Stripe, filesystem, terminal) — replaces ~10 hand-written adapters. Permission matrix
   and audit apply unchanged per call. MCP results are untrusted input (ROADMAP §26.11).
2. **LiteLLM (MIT)** as model gateway behind `core/routing` — provider fan-out, retries,
   per-agent virtual keys and budgets. Router keeps capability/privacy policy; provider keys
   move out of app env into LiteLLM.
3. **Mem0 (Apache-2.0)** on existing Postgres/pgvector behind `core/memory` — embedding/retrieval
   engine. The entity schema (clients/projects/people) remains custom.
4. **OpenHands (MIT)** as the Developer/QA agent execution engine, sandboxed in Docker,
   delegated to by `agents/developer`; all git writes approval-gated (`push_branch: allow`,
   `merge_main: ask_user`).
5. **n8n (Sustainable Use Licence)** for scheduled/autonomous workflows and as the **connector
   fabric** (1,500+ integrations incl. WordPress, WooCommerce, SharePoint, Stripe, client APIs).
   Two roles: (a) triggers that call `POST /api/v1/chat` to start governed, audited agent turns;
   (b) an **n8n MCP Server** that exposes selected workflows as governed tools consumed through
   the MCP adapter — so every n8n-fronted action still passes the permission engine and audit.
   Credentials live in n8n's vault, never in agents.
6. **Hermes Agent (MIT)** — optional, later — as a messaging-channel gateway
   (Telegram/WhatsApp/Signal) in front of the conversation API only; no tools or credentials in
   Hermes. SUNIL remains the brain.
7. **Ollama/vLLM Qwen** as a LiteLLM provider for the local-model phase; the privacy classifier
   enforces LOCAL-ONLY routing. The V3 fine-tuned personal model serves here too.
8. **OmniRoute** — registered behind LiteLLM as a **dev/experimentation lane only**, restricted
   to PUBLIC-classified workloads; never client or production data. Justification and limits in
   *Alternatives / limited adoption* below.
9. **Langfuse (MIT core)** — optional — analytics/evals subscriber on the trace spine;
   `audit_events` remain the source of truth.

Kept custom (the product): orchestrator + plan validation, permission engine + approvals,
audit spine, dashboard, entity memory schema, Codely Support tool, privacy classifier.

## Alternatives considered

- **Windmill** for scheduler/workflows (the earlier draft's choice). **Superseded by n8n:** n8n
  ships 1,500+ ready connectors (WordPress/WooCommerce/SharePoint/Stripe and the long tail Codely
  actually integrates), is MCP-native (workflows exposable as governed tools *and* an MCP client),
  and is lighter to operate for our mix. Windmill's native suspend-until-approval is not needed —
  SUNIL's own approvals queue (C4) is the approval point, not the workflow engine.
- **Adopt Hermes Agent as the platform.** Rejected: its LLM-driven loop and self-authored skills
  invert ROADMAP §25/§26/§33 (free-form output must not trigger privileged actions); approvals are
  command-centric, not agent × tool × operation; no multi-user identity; and M1 already delivers the
  control plane Hermes lacks. Retained as an optional channel surface only.
- **ContextForge MCP Gateway (IBM)** as the tool chokepoint. Rejected: with SUNIL's tool_framework +
  permission engine live and verified, a second gateway duplicates governance we already own. Revisit
  only if MCP server count or multi-instance federation grows beyond what the native adapter serves.
- **Graphiti** (temporal knowledge graph) for memory. Rejected for now: strongest temporal model but
  requires Neo4j — new ops surface vs Mem0 on the Postgres we already run.
- **OmniRoute in production.** Rejected for production use: free-tier evasion, prompt-mutating
  compression, and an unclear privacy posture make it unsafe for client/production data. Admitted
  **only** as a dev-lane provider for PUBLIC workloads, behind LiteLLM, so it inherits routing and
  audit and can be removed by config.
- **Build everything from scratch** (status quo). Rejected: months of commodity engineering
  (provider adapters, tool adapters, memory engine, workflow engine) with no product differentiation.

## Consequences

- V1 epic scope shrinks to integration + the custom product surface; delivery accelerates and runs
  as **parallel streams** (`V2_DEVELOPMENT_PLAN.md`) against frozen contracts.
- New third-party dependencies: pin versions; contract-test each MCP server; LiteLLM needs an HA plan
  or a documented direct-provider fallback (kill-switch = flip base URL back); n8n's Sustainable Use
  Licence confines it to internal use (no resale as a hosted service); OpenHands (beta) strictly
  sandboxed; OmniRoute fenced to the dev lane.
- The "models are replaceable resources" principle now applies to every integrated component: each
  sits behind a SUNIL-owned interface and can be swapped.
- Supersedes nothing in ADR-001..029; extends the plan of record. M1/M2/M9 are untouched.
