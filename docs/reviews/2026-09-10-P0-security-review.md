# Security Review — SUNIL V2 Phase 0 (Minions Team 21, Security Reviewer · Fable, 2026-09-10)

Reviewed branches: `task/P0-contracts` (SA) and `task/P0-platform` (DevOps), pre-merge.

## VERDICT

| Scope | Verdict |
|---|---|
| **task/P0-contracts** | **APPROVE with conditions** — security design genuinely strong; one cross-branch blocker (port inventory wrong against reality) plus shoulds |
| **task/P0-platform** | **BLOCK** — 0.0.0.0 port publishes (live at review time, violating ADR-032's own rule) and single-superuser Postgres (contradicts TB9) |
| **Overall Phase 0** | **BLOCK** until the three blockers land. All mechanical; no redesign. The branches touch disjoint files, so a merge would succeed textually while leaving docs and infra in silent contradiction — do not merge before reconciling. |

## Blockers

**B1 — cross-branch — the frozen config inventory points at the wrong Postgres and the wrong n8n.**
`ADR-032` table (`postgres 127.0.0.1:5432`, `n8n 127.0.0.1:5678`), `ARCHITECTURE_V2.md` §5 (`DATABASE_URL` default `...@localhost:5432/sunil`; `SUNIL_N8N_MCP_BASE_URL` default `http://localhost:5678/mcp`; Compose table), TB9, and the L-001 trace all disagree with the platform, which binds **5433** and **5680** (`infra/docker-compose.yml:74,180`). Ground truth verified on the machine: 5432 is an unrelated container (`strapi-next-starter-db-1`); 5678 is the unrelated host-native n8n build (netstat/docker ps). Consequence: a stream following the frozen §5 defaults sends SUNIL's Postgres credentials to a foreign database and `SUNIL_N8N_MCP_AUTH_TOKEN`, MCP calls and approval webhooks to a foreign n8n. ADR-033's validator cannot catch this — loopback-any-port is accepted. ADR-032's "fixed ports, changed only by ADR" rule was bypassed by the platform with no amendment. ARCHITECTURE_V2 §8's ".env.example regenerated from §5" as written would *undo* the platform's correct ports.
Fix: amend ADR-032 + ARCHITECTURE_V2 §5/TB9/§6 to host ports 5433/5680 (in-network `postgres:5432`/`n8n:5678` unchanged; ops `docs/ENVIRONMENT.md` §9 already correct); CI step asserting compose published ports == ADR-032 table.

**B2 — platform — every port published on 0.0.0.0, live at review time.**
`infra/docker-compose.yml:74,115,180` publish `"${POSTGRES_HOST_PORT:-5433}:5432"` etc. with no host IP → all interfaces. Verified live (`0.0.0.0:5433`, `0.0.0.0:5680`, `0.0.0.0:4000`). This is the configuration ADR-032 rejected by name. Exposure chain: n8n 2.x first-boot owner setup — whoever reaches :5680 first owns the vault that will hold every tool credential plus `SUNIL_SERVICE_TOKEN`; `restart: unless-stopped` keeps it reachable across reboots; with D-finding 1 the Postgres password may be the committed dummy.
Fix: `127.0.0.1:` prefix on all published ports (incl. commented api stub, line 218); CI assert every `published:` entry carries `host_ip: 127.0.0.1`; restart the stack after fixing.

**B3 — platform vs TB9 — one superuser owns all three databases.**
`infra/postgres/init/01-init-databases.sh:13-14` leaves `litellm`/`n8n` DBs owned by `POSTGRES_USER`; compose hands that same superuser to LiteLLM (line 103) and n8n (line 155). TB9 promises three role/password pairs — a LiteLLM or n8n compromise reads its own DB, not `audit_events`. As shipped, a compromised container holds the superuser credential for the server that will hold approvals + audit — it could flip an approval row to `approved`, which ADR-031's startup re-scan would then execute. The C4 CAS is only as trustworthy as write access to that table.
Fix (~10 lines): `litellm_user`/`n8n_user` with own passwords (two new env vars), each owns only its DB, `REVOKE CONNECT ON DATABASE sunil` from both; update two compose refs. **Before** streams boot volumes (init runs once per volume; later fix costs `down -v`).

## Findings — task/P0-contracts (should/nit)

1. `C4-approvals.md:§1` — **should** — `approved` rows never expire (consume CAS has no time bound; sweeper only expires `pending`). Hour-71 approval can execute days later after downtime; `binding_mismatch` rows stay `approved` forever. Fix: consume CAS adds `AND decided_at + <grace> > now()`; sweeper expires stale approved; re-scan finalises `approval_expired`.
2. `C4-approvals.md:§1` + `C1:§2.1` — **should** — crash between consume CAS and tool execution is fail-closed but leaves a `consumed` approval + permanently unfinalised task with no reconciliation. Fix: startup rule — consumed + unfinalised → finalise `failed`, named kind, audited.
3. `C1-tool-adapter.md:§2.1` — **should** — audit row written after execute; process kill mid-execution can fire a mutating side effect with zero `tool_calls` row (worst on the continuation path). Fix: two-phase audit — attempt row before execute (same transaction as consume for continuations), outcome update after.
4. `C1-tool-adapter.md:§3` — **should** — strip-list (`instructions`/`system`/`prompt` keys) is a bypassable denylist with unspecified case/nesting semantics that mutates legitimate data. Load-bearing control is §25/§33.3; define strip as recursive+case-insensitive cosmetic defence-in-depth, or drop it.
5. `ADR-035` / C5 — **should** — inbound `Authorization`/`Cookie` log redaction unstated. Fix: one normative line + contract test.
6. `ADR-035` — **should** — structural route scope probed by a single negative test; router-level dependency slip would widen the lane silently. Fix: build-time test iterating `app.routes` asserting the bearer dependency exists on exactly `POST /api/v1/chat`.
7. `C5-chat.md:§2.3` — **should** — service-lane conversation scoping unspecified (bearer holder can post into any owner conversation / read history-derived output). State blast radius or restrict lane to conversations it created.
8. `C4-approvals.md:§4` — **nit** — `summary` embeds attacker-influenceable values (repo names, issue titles). Rendering rule for Stream D: plain text only in the approval card.

**Verified sound:** C4 state machine (complete CAS transition table, no default reads as decided, replay→409, decide-race one winner, TOCTOU closed by `(agent_id, tool, operation, args_hash)` binding recomputed at consume, no service-level bypass mode); ADR-035 fail-closed + constant-time compare + rotation; ADR-033 kill switch genuinely population-scoped, named-host set a frozen code constant (residual: loopback-any-port — exactly why B1 boots silently); ADR-034 config-authoritative, `readOnlyHint` inert, renaming cannot mint capability; C5 — no path from free-form output to privileged action; **C2's `CompletionRequest` has no `tools` field at all**, preserving M1's strongest T-15 control by contract shape.

## Findings — task/P0-platform (beyond B2/B3)

1. `scripts/dev-up.*` + `.env.example` — **should** — dev-up auto-copies `.env.example`→`.env` and the preflight only checks non-emptiness, so committed dummies pass and the stack runs on known secrets. Fix: preflight rejects `dummy|change-me`, or copy step generates random values.
2. `infra/docker-compose.yml:22-23` — **should** — the empty-string "fails loudly" convention is false for n8n (empty `N8N_ENCRYPTION_KEY` → silently self-generates, vault key unmanaged) and unverified for LiteLLM on the pinned tag. Fix: `${VAR:?set in .env}` for the four secrets; run compose-validation with `--env-file .env.example`.
3. `.github/workflows/ci.yml:117-124` — **should** — secret-scan placeholder filter runs against whole lines including the filename, so any hit in `.env.example` is silently dropped (demonstrated). Fix: apply the filter to matched content only, or allowlist literal dummy strings.
4. `ci.yml` — **nit** — actions pinned by tag not SHA.
5. `infra/litellm/config.yaml:96` — **nit** — `drop_params: true` can silently drop `response_format`; record that the app-side validator is load-bearing, gateway best-effort.

**Verified sound on the platform:** no privileged containers / docker.sock / cap_add; n8n hardening good (`N8N_BLOCK_ENV_ACCESS_IN_NODE=true`, runners on, diagnostics off); images pinned exactly with CI floating-tag guard; LiteLLM message-logging off; OmniRoute lane commented out with correct PUBLIC-only fencing; init script quoted + `ON_ERROR_STOP`; `.gitignore` correct; **CI ASCII guard fail-open fix genuinely closed**; CI injection surface clean (`pull_request`, `contents: read`, zero `secrets.*`, no attacker-controlled interpolation); independent secret scan of both branches: no hits.

## Must be re-checked at build (owner-visible list)

1. Lane-flag invisibility → import/reference tripwire on `core/routing` (Stream B).
2. Bearer route-table-wide scope test (Stream E/QA).
3. C5 exactly-one envelope rule against the real route (QA).
4. Redaction coverage of inbound `Authorization`/`Cookie` + `error_message` paths (Stream A/QA).
5. Plan-step params immutability — plan schema must forbid templating later-step params from earlier tool output, else THREAT_MODEL §5.1 control 2 / DC-1 expires early (Architect, at plan-schema definition).
6. Consume-CAS + attempt-audit in one transaction (Stream D).
7. LiteLLM empty-master-key behaviour on `v1.83.14-stable.patch.3` (DevOps).
8. `SUNIL_N8N_MCP_AUTH_TOKEN` actually enforced by the n8n MCP endpoint (Stream E).

Memory/advisory hygiene: no instruction-shaped content found in central-memory brief or reviewed files.

**Conditions to lift the BLOCK:** B1 (ADR-032 amendment + ARCHITECTURE_V2 §5/TB9/§6 to 5433/5680), B2 (`127.0.0.1:` + CI assert + stack restart), B3 (three DB roles before any stream boots a volume). Re-verification against the merged tip required.
