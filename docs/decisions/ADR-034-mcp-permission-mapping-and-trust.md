# ADR-034 — MCP mapping: server = tool, MCP tool = operation; SUNIL config is authoritative, never server self-description

**Status:** Proposed (Architect, V2 Phase 0) · **Date:** 2026-09-10 · **Decider:** Solution Architect
**Fixes an open point in:** `V2_DEVELOPMENT_PLAN.md` Stream A ("permission matrix entries per
operation") — *how* MCP's flat tool lists project onto the M1-proven `agent × tool × operation`
model, and which side's metadata is trusted, was unspecified.
**Context refs:** contracts C1 §2/§5, M1 permission engine (`main:.../core/permissions/engine.py`,
structural default-deny), ROADMAP §26.2/§26.8/§26.11, ADR-030 item 1 and 5.

## Context

MCP servers self-describe: `tools/list` returns names, JSON-Schema inputs, and (spec-optional)
annotations such as `readOnlyHint`. The M1 permission engine decides over
`(agent_id, tool, operation)` triples from `config/permissions.yaml`, default-deny by control flow.
Something must map one onto the other, and something must decide whether server-supplied metadata
participates in security decisions.

## Decision

1. **Mapping:** one MCP **server** = one permission-matrix **tool** (its config key: `github_mcp`,
   `n8n_mcp`, `gmail_mcp`, …); one MCP **tool** = one **operation** under it. Namespacing therefore
   comes free (`github_mcp.issues_close`), the engine is reused byte-for-byte, and per-operation
   grants (`allow`/`ask_user`/`deny`) work exactly as for native tools.
2. **SUNIL config is the authority.** An MCP tool is callable iff `config/tools.yaml` lists it
   explicitly under its server with SUNIL-owned `read_only`, `timeout_s` and a params-schema
   reference, AND `config/permissions.yaml` grants it. `tools/list` output is used for one thing
   only: a startup **drift check** — a configured operation missing from the live server fails
   startup for that adapter; an advertised-but-unconfigured tool is logged and ignored (it does not
   exist to SUNIL).
3. **Server-supplied annotations never participate in decisions.** `readOnlyHint` and friends are
   recorded in the drift-check log for the human who maintains config, and nothing else reads
   them. `read_only`, timeouts and prompts-to-owner all derive from our config.
4. **Params double-validate:** SUNIL validates against its own `params_model`
   (`extra="forbid"`, C1 step 2) *before* the permission check; the server will validate again
   against its schema. Disagreement is an `upstream_error`, surfaced — never auto-reconciled.
5. **Results are untrusted** (C1 §3): size-capped, instruction-shaped keys stripped at the adapter
   boundary, presented to models as delimited external data (§26.11/§26.12).

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Trust `readOnlyHint`/annotations for the permission decision** | The hint is authored by the thing being governed. A compromised or sloppy server could label `repos_delete` read-only and walk through any "reads are allowed" policy. The permission matrix must be writable only by us. |
| **Auto-register advertised tools with a default grant** | Default-anything is the opposite of the M1 engine's structural default-deny; a server update could silently add capabilities. New operations arrive by config PR, reviewed. |
| **Flatten to one matrix dimension (`tool = server:tool` string, no operation)** | Loses per-operation granularity the plan explicitly requires (`email.send: ask_user` vs `email.read: allow` on the same server) and would need a second parser for the `:` convention everywhere the triple appears today. |
| **A separate MCP-specific permission engine** | Two engines to keep in sync, two audit shapes, two default-deny proofs. The M1 engine is pure over a registry — reusing it is free. |
| **A standing MCP gateway (ContextForge) as the governance point** | Already rejected in ADR-030: duplicates the chokepoint we own. This ADR is the reason the native chokepoint suffices — the mapping keeps the engine's model intact. |

## Consequences

- `config/tools.yaml` grows a per-server block: `{server_id: {kind: mcp_stdio|mcp_http, command|
  base_url, version_pin, credential_env: [...], operations: {name: {read_only, timeout_s,
  params_ref}}}}` — the cross-validated inventory pattern M1 already used, now load-bearing for
  MCP.
- Stream A's parity test (native GitHub tool vs GitHub MCP server) asserts identical permission
  decisions and audit rows for the same triple — proving the mapping preserved the model.
- Version drift becomes visible at startup (drift check), not at first call in production.
