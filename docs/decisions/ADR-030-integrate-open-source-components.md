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

---

## Amendment 1 — clean-slate rebuild on branch `V2` (owner decision, 2026-09-10)

The owner directed that the `V2` branch start **empty of application code**: the M1 build
(`apps/`, `config/`, `scripts/`, plus the pre-reset `prototype/` mockups and V1 CI) was removed
from `V2` in this commit. This changes one premise of this ADR — "plugs into existing seams"
becomes "**rebuilds those seams fresh on `V2`**":

- **`main` keeps the complete live-verified M1 build** (564 tests, live turn 2026-08-19). It is
  the reference implementation and fallback, not deleted history.
- The component decisions above (what to integrate, what stays custom, what was rejected) are
  **unchanged**. The custom product surface — gateway, orchestrator + plan validation, permission
  engine + approvals, audit spine, dashboard, entity schema — is now **built new on `V2`**,
  integration-first, using the M1 code on `main` as the informing reference.
- `V2_DEVELOPMENT_PLAN.md` Phase 0 contracts C1–C5 are therefore **greenfield interface
  definitions** (informed by M1's proven shapes) rather than documentation of existing code.
- ROADMAP §25/§26/§33 rules (validated plans, permission chokepoints, full audit) apply to the
  rebuild unchanged; M2/M9 (streaming, voice) remain scoped to `main`'s build and their designs
  carry over as requirements for the rebuilt gateway.

Risk accepted by the owner: the rebuild forgoes the shortcut of reusing verified code in place;
mitigation is that `main` remains runnable and diffable throughout.

---

## Amendment 2 — memory engine: first-party pgvector provider; Mem0 demoted to selectable-unbuilt (Architect ratification, 2026-09-12)

Ruling **R9** (`docs/tasks/integration-w1-rulings.md`) ratifies Stream C's wave-2 engine choice:
the C3 memory seam is served by the first-party **`PgVectorMemoryProvider`**
(`apps/api/sunil/memory_providers/pgvector_provider.py` — direct SQL on the Postgres/pgvector this
stack already runs), **not** by Mem0-the-library. Decision item 3 above is amended to read:

> 3. **Memory: first-party engine on existing Postgres/pgvector behind `core/memory` (C3).** The
>    entity schema (clients/projects/people) remains custom. **Mem0 (Apache-2.0) remains an
>    admitted, swappable vendor for this seam — selectable (`SUNIL_MEMORY_PROVIDER=mem0`) and
>    deliberately unbuilt**, resolving to a loud `SeamUnavailable` naming
>    `memory_providers/mem0_provider.py`, never a silent fallback: an operator who configured Mem0
>    must not quietly get different retrieval.

**Grounds — conformance, not taste** (the lane's S2-C §1 rationale, verified against C3's frozen
text):

1. **Mem0's write path is an LLM.** `mem0.add()` routes stored content through a model that
   decides ADD/UPDATE/DELETE and rewrites the stored fact. C3 §2 forbids the provider
   re-classifying already-scrubbed content in as many words, and §4a is exact arithmetic on a
   four-value privacy lattice — a rule a probabilistic rewrite cannot satisfy, let alone satisfy
   repeatably in a contract test.
2. **Schema and dependency posture.** Mem0's store has no `privacy` column — the field the whole
   of §4a turns on — and it drags an LLM + embedder dependency chain whose parity proof is
   unrunnable on a machine holding no provider key.
3. **The vendor's audit buys nothing.** C3 already places the audit row outside the vendor
   (`audit_event_id` echo), so behind Mem0 that discipline is adapter code anyway.

**What survives unchanged is this ADR's principle.** The seam is the decision: C3 stays frozen,
the engine behind it is swappable, and keeping the unselected vendor *selectable and loud* is the
principle honoured, not abandoned. ADR-013's premise also lands intact: pgvector on the
already-provisioned image, `CREATE EXTENSION vector` plus one additive migration (`0005`) — exactly
the shape that ADR reserved.

**Rejected alternatives:**

- **Order Mem0 built anyway.** Requires either violating C3 (vendor re-classification of stored
  facts) or wrapping Mem0 so thickly (shadow privacy store, write-path bypass, §4a re-implemented
  in the adapter) that the vendor contributes only its bug surface. Building the same guarantees
  directly on the database we run is the smaller system.
- **A standalone ADR-037.** Fragments the component register: item 3 lives in this file, Amendment
  1 already set the in-file amendment pattern, and a reader of the decision list must meet the
  correction in the same document that states the decision.
- **Removing `mem0` from the selectable set.** Erases the replaceability evidence; the loud
  `SeamUnavailable` is the documented, tested seam posture for the alternative engine.

**Consequences:** C3 moves to v1.1.1 (descriptive vendor prose corrected; changelog there);
`ARCHITECTURE_V2.md` §5's `SUNIL_MEMORY_PROVIDER` row corrected the same day. The
privacy-relevant embedding path is ruled separately: routing and budgets ride the LiteLLM gateway
today; the `llm_calls` audit half is a registered **C2 v2.0.0 candidate** (`embed()` on the frozen
protocol — ruling R10).
