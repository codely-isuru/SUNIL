# Task — P0-contracts: V2 Phase 0 contract freeze + rebuild architecture

Owner (solution_architect) · Status: **fix round complete (2026-09-10) — awaiting QA/Security re-review**
**File ownership:** `docs/contracts/**`, `docs/ARCHITECTURE_V2.md`,
`docs/decisions/ADR-031..035*.md`, `docs/decisions/README.md` (table append only),
`docs/tasks/P0-contracts.md`. No app code (Phase 0 platform/fake implementation is a separate
task per the plan).

## Static spec (from the V2 development plan, Phase 0)

- **Background:** ADR-030 Amendment 1 — clean-slate rebuild on `V2`; `main` holds the M1 reference
  build. Six parallel streams need frozen seams before any code.
- **Objective:** freeze C1–C5 as versioned greenfield contracts (informed by M1 shapes), each with
  a QA-buildable fake spec; publish the rebuild architecture with trust boundaries, config
  inventory and the L-001 mutating-request trace; record every open-point decision as an ADR with
  rejected alternatives.
- **Acceptance criteria:** five contracts v1.0.0 with buildable fakes; C4/C5 valid OpenAPI 3.1
  (yaml parses clean); ARCHITECTURE_V2.md contains the traced mutating request + complete config
  inventory; ADRs argued with rejected alternatives; decisions README table updated; granular
  commits pushed to `origin task/P0-contracts`.
- **Security considerations:** §25/§26/§33 non-negotiables; central-memory lessons applied —
  approvals state machine has no schema default and no service-level bypass mode (2026-08-17 ×2);
  full transition enumeration (2026-08-05); funding/auth verified for LiteLLM/Mem0/n8n (2026-08-05).
- **Rollback:** documents only — revert the branch.
- **Documentation needs:** this is the documentation.

## Cross-lane consumers

- `docs/contracts/C1..C5` → consumed by Streams A–F and by the Phase 0 platform task
  (fakes + contract suites + Compose implement exactly these specs).
- `docs/decisions/README.md` table rows 031–035 → consumed by any later ADR author (numbering).
- `docs/ARCHITECTURE_V2.md` §5 → consumed by the platform task (`.env.example`,
  `docker-compose.yml` are generated from it).

## Progress

- [2026-09-10 | solution_architect] Read plan/ADR-030+A1/roadmap §24-26/§33; inspected M1 reference
  shapes read-only via `git show main:` (tool_framework/base.py, permissions/engine.py,
  api/schemas.py, routes/chat.py, settings.py, memory/short_term.py, deps.py — confirmed
  `X-SUNIL-Client: web`); ran central memory brief (no instruction-shaped content found; lessons
  applied and cited in C4/ADR-033).
- [2026-09-10 | solution_architect] Committed, in order: C1 (tool adapter + hooks + fake), C2
  (provider/gateway + FakeProvider), C3 (memory recall/write + FakeMemoryProvider), C4 (OpenAPI
  3.1 + rationale + FakeApprovalsService — yaml parse-verified), C5 (OpenAPI 3.1 + rationale +
  StubTurnExecutor v2 — yaml parse-verified), ADR-031..035 + README table/amendment index,
  ARCHITECTURE_V2.md (TB1–TB9, §5 inventory, §6 L-001 trace), this file. Handed to Delivery
  Manager for owner Gate 2.
- [2026-09-10 | solution_architect] **Fix round** on the QA (7 blockers) + Security (1 blocker,
  8 shoulds) reviews: all 7 contract blockers fixed, all 8 Security shoulds fixed, all 9 QA
  contract should-fixes fixed, plan-literal build-check rule added — see Issues table for
  per-finding disposition. Contracts stay v1.0.0 (freeze never merged) with a Changelog section
  each. ADR-031 Amendment 1 (consume ownership → Tool Manager) and ADR-032 Amendment 1 (real
  host ports 5433/5680/3001, `infra/` compose path, profiles deferred, CI port-parity check)
  appended per the no-silent-edit convention; ADR-033/035 annotated in place, dated. C4/C5
  OpenAPI re-linted (yamllint, ops config, exit 0) and re-parsed clean. 7 granular commits
  pushed to `origin task/P0-contracts`; branch NOT merged (reviewer gate).

## Issues

Reviews of 2026-09-10 (`docs/reviews/2026-09-10-P0-qa-review.md`,
`…-P0-security-review.md` on `V2`). Disposition of every finding assigned to this task —
**all fixed, none accepted-without-fix**; each contract carries a Changelog naming its changes.

| Finding | Where | Severity | Disposition |
|---|---|---|---|
| QA B1 — hook fakes unspecified; tests 3–4 presuppose an unnamed grant API | C1 §6 | blocker | **Fixed** — §6 table of four fakes; `FakePermissionHook.grant()` exact, `RecordingAuditHook` two-phase, approvals fake = C4 §6 verbatim; tests 1–7 rewritten with fixture + ordering probe |
| QA B2 — `approval`/`trace` types undefined | C1 §2.1 | blocker | **Fixed** — typed `execute` signature; `TraceContext` dataclass; `approval: str \| None` = the C4 approval id (opaque, manager recomputes binding) |
| QA B3 — consume-twice contradiction | C1 §2.1 vs C4 §1/§3 | blocker | **Fixed** — ONE owner: the Tool Manager consumes via `ApprovalsService.consume` (seam replaces `ParkHook`); C4 §3's executor-side consume path deleted; ADR-031 Amendment 1; C1 test 5 now satisfiable; CAS single-use property untouched (Security verified-sound list preserved) |
| QA B4 — `WriteReceipt.audit_event_id` unobtainable | C3 §2/§5 | blocker | **Fixed** — keyword-only `audit_event_id: str` parameter on `write`, echoed in the receipt; parameter-not-item-field argued in §2 |
| QA B5 — five incompatible dedupe/privacy statements | C3 §5 vs §4 | blocker | **Fixed** — single rule §4a (merge = stricter label survives, never raises; genuine widening = laxer-labelled duplicate APPEND, rejected `invalid_privacy_transition`); test 3 disambiguates (a)/(b)/(c) |
| QA B6 = Security B1 — frozen port inventory wrong vs platform reality | ADR-032, ARCH §5/TB9/§6 | blocker | **Fixed** — ADR-032 Amendment 1 (dated, this fix round): host ports postgres 5433 / n8n 5680 / web 3001, in-network unchanged; compose at `infra/docker-compose.yml`; profiles deferred until the api container exists; **CI parity check required (DevOps implements)**; ARCH §2/§4/§5/§6/§8 regenerated; ADR-033/035 annotated in place, dated |
| QA B7 — C2 model example is an upstream id | C2 §2/§3 | blocker | **Fixed** — DM ruling recorded: gateway alias namespace authoritative (`claude-sonnet`, `claude-opus`, `claude-haiku`, `gpt-flagship`, `gpt-mini`); `models.yaml` ids MUST equal the gateway `model_name` set; startup `/v1/models` parity check (`GatewayModelParityError`); `provider_model_id:` for the direct lane |
| Security 1 — approved rows never expire | C4 §1 | should | **Fixed** — consume CAS bound by `decided_at + SUNIL_APPROVAL_CONSUME_GRACE_HOURS` (default 1, in ARCH §5); `approved→expired` transition added (sweeper + lazy-at-consume); re-scan finalises `approval_expired`; fake + test 7 |
| Security 2 — consumed+unfinalised has no reconciliation | C4/C1 | should | **Fixed** — C4 §3 startup rules 1–3; rule 3 finalises `failed` with new kind `continuation_interrupted` (C5 enum, reconciliation-only), audited `continuation_reconciled`; never re-executes |
| Security 3 — audit written after execute | C1 §2.1 | should | **Fixed** — two-phase `AuditHook.attempt/finalise`; attempt BEFORE execute; same-transaction-as-consume rule for continuations; C1 test 7 ordering probe |
| Security 4 — strip-list semantics/status | C1 §3 | should | **Fixed** — recursive + case-insensitive, logged with key path; declared cosmetic defence-in-depth; §25/§33.3 named load-bearing |
| Security 5 — inbound `Authorization`/`Cookie` logging unstated | C5/ADR-035 | should | **Fixed** — normative redaction rule in C5 §3 + contract test 7 (valid AND invalid credentials probed) |
| Security 6 — single negative test for route scope | C5/ADR-035 | should | **Fixed** — C5 contract test 8: iterate `app.routes`, bearer dependency by identity on exactly `POST /api/v1/chat` |
| Security 7 — service-lane conversation scoping | C5 §2.3 | should | **Fixed** — lane restricted to conversations it created (404 otherwise, no existence oracle); blast radius stated; `FakeConversationStore` fixture + test 9 |
| Security 8 — approval-card `summary` rendering | C4 §4 | nit/should | **Fixed** — plain-text-only rule in C4 §4 + both OpenAPI `summary` descriptions (`params_redacted` values included) |
| Security build-check 5 — plan params templating | plan schema | build-check | **Fixed now** — normative plan-literal rule in C2 §2 (THREAT_MODEL §5.1 control 2 / DC-1), cross-ref in C1 §2.1 step 2; Streams A/B inherit it |
| QA should — `invalid_output` ownership | C2 §4 vs §5 | should | **Fixed** — DM ruling recorded: retries SUNIL-side (`core/routing/retry.py` is the named re-asker); adapter raises; gateway MUST run `num_retries: 0`, `drop_params: false` (DevOps applies) |
| QA should — `FAIL:invalid_output` with `json_schema=None` | C2 §5 | should | **Fixed** — echo lane, not special |
| QA should — streaming projection unsatisfiable | C2 §5 / C5 §4 | should | **Fixed** — whitespace-preserving partition (`re.findall(r"\S+\s*\|\s+", text)`); byte-for-byte tests on fixtures with double space/newline/leading whitespace |
| QA should — `unknown_project` no fake/test | C5 §4 | should | **Fixed** — `NOPROJ:` stub row + test 1 coverage |
| QA should — `HeartbeatFrame` stray `description` property | C5 yaml | should | **Fixed** — property removed, schema-level description added; yamllint + parse clean |
| QA should — `credential_env:`→`Settings` mapping | C1 §5 | should | **Fixed** — exact UPPER_SNAKE→lowercase `SecretStr` mapping; missing/unset → `ToolAdapterStartupError` at wiring time |
| QA should — C3 recall tiebreaker unreachable/lexicographic | C3 §5 | should | **Fixed** — write-order-descending; test 5 asserts equal-score ordering |
| QA should — `POST /api/v1/approvals` absence unexplained | C4 | should | **Fixed** — scope note in C4 §5 (park-transaction invariant; cross-ref ADR-031) |
| QA should — pgvector image floats | ARCH §5 | should | **Fixed** — pinned `pgvector/pgvector:0.8.6-pg17` (litellm/n8n pins recorded too) |
| QA nits (channel_label enum wording, NDJSON single-frame schema note, contracts-branch lint config) | various | nit | **Open, deliberate** — not in the DM's fix list and none blocks fake-buildability; carried to the next contracts touch |

Everything on Security's verified-sound list was preserved unchanged: C4 CAS transition table
(extended, not weakened — two new transitions are themselves CAS-guarded), no-default-decides,
C2's no-`tools` `CompletionRequest` shape, ADR-033 population scoping, ADR-034
config-authoritative.

## Questions (proceeding on stated assumptions rather than stalling)

1. **Postgres from day one** (ARCHITECTURE_V2 §1): the plan's platform task adds the Postgres
   container anyway; I made it the app default on V2, keeping ADR-001's portable schema (SQLite
   for unit tests). If the owner prefers SQLite-default as on M1, only §5's `DATABASE_URL` default
   changes — no contract changes.
2. **Approval TTL default 72 h** (C4/§5): owner may prefer shorter for destructive ops;
   per-operation TTLs are a v1.1 additive extension if wanted.
3. **`input_modality=voice` is 422 until the voice milestone is rebuilt on V2** (C5 §2.2) —
   assumed acceptable since M9 designs carry over as requirements, not code (ADR-030 A1).

## Outcome

- Commits (branch `task/P0-contracts`, pushed): C1..C5 contracts, ADR-031..035 + README,
  ARCHITECTURE_V2.md, task file — see `git log --oneline a263193..`.
- Test evidence: C4/C5 YAML parsed clean with PyYAML (documented in Progress); no code claimed.
- Notes: Phase 0 exit additionally requires the platform task (fakes, contract suites, Compose
  boot) which builds FROM these specs; that task is not this one.
