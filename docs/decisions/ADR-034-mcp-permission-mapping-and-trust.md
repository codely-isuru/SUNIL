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
   *[⚠ §1's implicit identity — operation name = advertised server-tool name — became the
   DEFAULT of a per-operation `server_tool:` binding by **Amendment 1** (below, 2026-09-17,
   ruling R16 part 3): names are SUNIL's, bindings track the vendor. Original text kept verbatim
   per the no-silent-edit convention; read the amendment as current.]*
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
  MCP. *[Amendment 1 (2026-09-17) adds optional `server_tool` to the per-operation keys.]*
- Stream A's parity test (native GitHub tool vs GitHub MCP server) asserts identical permission
  decisions and audit rows for the same triple — proving the mapping preserved the model.
- Version drift becomes visible at startup (drift check), not at first call in production.

---

## Amendment 1 — per-operation `server_tool:` bindings, the bounded `merge_main` composition, and the naming law (2026-09-17, Solution Architect; registered by ruling R16 part 3, 2026-09-12)

**Why:** R16 (`docs/tasks/integration-w1-rulings.md`, 2026-09-12) retired the deprecated
`github_mcp` pin: its captured `tools/list` advertised **none** of SUNIL's four operation names,
and no GitHub-API MCP server anywhere advertises a branch-merge tool at all. §1's implicit rule —
the operation name IS the advertised tool name — cannot survive a vendor catalogue SUNIL does not
author. This amendment is w2r3 re-landing parcel item 1 (the instrument moves when the change
moves — R4/R10 precedent); the github lane implements against it, and the bindings it admits are
confirmed or corrected by that parcel's step-0 verbatim `tools/list` capture.

1. **Naming law (governs the other two points).** SUNIL's operation names are **governed
   vocabulary**: they appear in permission rows, approval cards, audit history and ADR-030 §4's
   own text, and they NEVER track a vendor. A vendor swap changes bindings, never names —
   `merge_main` stays `merge_main` whether the executor is one vendor verb, two composed verbs,
   or a native adapter. Renames of governed names are decisions of this ADR line, not of any
   capture.
2. **Per-operation `server_tool:` binding (§1 gains a key).** Each operation under a server MAY
   declare `server_tool: <advertised-tool-name>`; **default = the operation name**, so every
   existing block (e.g. `n8n_mcp.run_workflow`) keeps §1's original behaviour byte-for-byte with
   no config edit. The startup **drift check (§2) verifies the BINDING**, not the SUNIL name: a
   bound server tool missing from live `tools/list` refuses `start()` exactly as an unserved name
   did. **Invocation calls the binding**; the SUNIL name still keys permissions, approvals and
   audit. Fixed-argument translations stay adapter-side and SUNIL-owned (e.g. the expected
   `issues_close → update_issue` binding fixes `state=closed` in the adapter; the params model
   still admits no `state` field, so the approval card keeps reading "close issue N").
3. **Bounded composition — admitted per named operation, today exactly `merge_main`.** Where no
   single advertised tool can serve a governed operation, `server_tool:` MAY bind an **ordered
   list** — for `merge_main`: `[create_pull_request, merge_pull_request]`
   (`create_pull_request(branch → base)` then `merge_pull_request(number)`) — executed as **ONE
   governed operation**: one permission row, one C4 approval bound to exactly
   `{project_key, branch, base_branch}`, one audit trail. The **PR number is derived state minted
   inside the approved execution — never plan input**, never a params field, never separately
   approved. The drift check verifies **every** listed binding; any one missing refuses
   `start()`. The sequence is fixed in config and executed by SUNIL-owned adapter code — the
   model plans `merge_main`, never the steps. A list binding is admissible only for an operation
   this ADR line names (a new composition = a new amendment). If the w2r3 capture reveals a
   direct branch-merge tool, bind that single tool instead — the composition is the ruled
   fallback shape, and it is an upgrade rather than a workaround: the owner's approval gains a
   server-side reviewable PR trail.

Decisions 2–5 of the original are unchanged: SUNIL config remains the sole authority (bindings
live in `config/tools.yaml` and change by reviewed PR, never by server advertisement), server
annotations still decide nothing, params still double-validate against SUNIL's models, results
stay untrusted.

### Rejected alternatives (this amendment)

| Rejected | Why |
|---|---|
| **Direct vendor names in config (rename SUNIL's operations to the server's verbs)** | Bleeds vendor vocabulary into permission rows, approval cards, audit history and ADR-030 §4 — churn on every future vendor swap — and at ruling time would have traded four unserved names for four **unverified** ones (nothing offline confirmed the successor's verbs). The governed vocabulary must be writable only by us — the same argument as decision 2. |
| **Per-call free composition (the planner chains server tools ad hoc)** | Composition decided at plan time is composition decided by the model: the approval card could no longer state what will happen, the permission row would govern fragments instead of the intent, and derived state (the PR number) would round-trip through plan input — exactly what point 3 forbids. Compositions are declared in config, fixed in code, approved as one intent, or they do not exist. |

### Changelog

- **2026-09-10** — original decision (mapping, config authority, untrusted annotations/results,
  double validation).
- **2026-09-17** — **Amendment 1**: `server_tool:` bindings (drift check verifies bindings;
  default = operation name), the bounded `merge_main` composition (one governed operation; PR
  number never plan input), the naming law (operation names are SUNIL's, never vendor-tracking).
  Registered by R16 part 3 (2026-09-12); implemented by the w2r3 github re-landing parcel.
