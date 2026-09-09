# ADR-033 — Egress URLs: ADR-017's rule, extended with a closed set of named Compose hosts

**Status:** Proposed (Architect, V2 Phase 0) · **Date:** 2026-09-10 · **Decider:** Solution Architect
**Extends (does not amend):** ADR-017 — its canonical-or-loopback rule is unchanged and still
governs the direct-provider lane. This ADR adds the case ADR-017 could not foresee: gateways that
have **no public canonical host** because we host them ourselves.
**Fixes an open point in:** `V2_DEVELOPMENT_PLAN.md` Stream B ("`core/routing` pointed via C2
settings") — pointed at *what*, validated *how*, and with what kill switch was unspecified.
**Context refs:** ADR-030 (LiteLLM, n8n), ADR-032 (topology), contracts C2 §3, C4 §2, C1 §5.

## Context

ADR-017's rule — every upstream base URL equals its canonical public value or is loopback, enforced
at `Settings` construction, or the app refuses to boot — exists because an env-settable, unguarded
base URL is an exfiltration channel (it carries `Authorization` headers to whatever host is named).
V2 adds SUNIL-side URLs whose *correct* value is neither canonical-public nor, in the Compose full
profile, loopback: the LiteLLM gateway (`http://litellm:4000`), the n8n MCP server
(`http://n8n:5678/mcp`), and the approval webhook (`http://n8n:5678/webhook/...`).

## Decision

One shared validator (rebuilt `settings.py`), applied to every outbound base URL field:

```
valid(url) ⇔ url == canonical(field)            # ADR-017, unchanged (direct-provider lane)
           ∨ host(url) is loopback              # ADR-017, unchanged (test doubles)
           ∨ host(url) ∈ {"litellm", "n8n"}     # NEW: closed, literal, code-level set
```

- The named-host set is a **frozen constant in code**, not configuration: adding a host is a code
  change with review, never an env edit. It contains exactly the Compose service names from
  ADR-032 that SUNIL legitimately calls (`openhands` joins it in Phase V2-D via a version bump of
  this ADR's table in `ARCHITECTURE_V2.md` §5).
- Fields governed from Phase 0: `SUNIL_LLM_GATEWAY_BASE_URL` (default `http://localhost:4000`),
  `SUNIL_N8N_MCP_BASE_URL` (default `http://localhost:5680/mcp` *[was `:5678`; default moved by
  ADR-032 Amendment 1, 2026-09-10 — the validator rule here is unchanged]*),
  `SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL` (optional), plus ADR-017's existing
  `ANTHROPIC_BASE_URL`/`OPENAI_BASE_URL` (direct lane, canonical-or-loopback only).
- **Kill switch, population-scoped:** `SUNIL_LLM_PROVIDER_LANE=gateway|direct` (default `gateway`)
  selects transport wiring at startup. It is readable **only** by provider registration; the Model
  Router's capability/privacy policy runs before provider selection and cannot see the lane flag —
  so flipping the lane can never widen which workloads reach a cloud provider (central-memory
  lesson 2026-08-17: the excluded population's decision must not take the mode as input).
  `LOCAL_ONLY` routing fails closed in both lanes until a local provider exists.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Allow any RFC-1918/private-range host** | Private ranges include the whole LAN — a redirected gateway URL would carry every prompt and virtual key to any machine on the network. The legitimate set has two members; enumerate them. |
| **A configurable allow-list env var (`SUNIL_ALLOWED_EGRESS_HOSTS`)** | Moves the guard into the same trust domain as the value it guards: whoever can set the base URL can extend the list. ADR-017's strength is exactly that the safe set is unreachable from the environment. |
| **Docker-network isolation instead of URL validation** | Only holds in the full profile; the daily dev loop runs the API on the host where no network namespace applies. Also fails silently — a wrong URL should refuse to boot, not time out. |
| **Skip validation for "internal" URLs (trust the operator)** | The threat is not the operator, it is anything that can influence process env (a sourced script, a copied `.env`, a CI variable). Same argument ADR-017 already won. |
| **A kill switch per provider inside the router policy** | Puts transport state inside the policy engine, exactly where the 2026-08-17 population-scoping lesson says it must never live; router policy stays pure over `(capability, privacy_class)`. |

## Consequences

- `Settings` construction is the single enforcement point; every governed field lists its
  validator in `ARCHITECTURE_V2.md` §5 so the config inventory and the mechanism can be checked
  against each other (L-001).
- QA's loopback doubles keep working unchanged in both lanes.
- The n8n MCP server and webhook URLs inherit the guard for free — Stream E cannot accidentally
  point approvals notifications at the public internet.
