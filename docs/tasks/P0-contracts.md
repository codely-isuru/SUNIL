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

## C3-scope round (2026-09-10, branch `task/P0-c3-scope` — post-merge, post-fakes-build)

Adjudication of the QA fakes-build findings (`docs/tasks/P0-fakes.md`) plus the security-delta
residuals S-1..S-5 assigned to the contract owner.

| Item | Where | Disposition |
|---|---|---|
| F-1 blocker — `write` carries no scope | C3 §2/§4a/§5 | **Fixed, v1.1.0** — `write(item, rules, *, scope: MemoryScope, audit_event_id: str)`; parameter-not-field argued in §2 (addressing of the call; §3 resolution rule; no vendor-persisted scope copies); §4a/§5 grounded on the parameter; contract test 7 pins the new signature. MINOR-not-MAJOR classification defended in the changelog (restores the document's own frozen semantics; v1.0.0's write path was self-contradictory and unimplemented) |
| QA call — `decide` returns `Approval \| StateConflict \| None`, unknown id → 404 | C4 §6.2 | **Blessed, normative, v1.0.1** — `None` = unknown id → §5's 404 (already in the YAML); conflict and absence are return values, status-code mapping lives only in the HTTP layer |
| QA call — `ToolManagerProtocol` in `base.py`, concrete pipeline in `manager.py` | C1 §2.1 | **Blessed, recorded, v1.0.1** — matches ARCHITECTURE_V2 §2's layout (`base.py, manager.py (the chokepoint)`); a concrete class in the transcription module would be a vacuous-pass risk and QA must not author what it tests |
| S-1 driver-token drift | ARCH §5 / .env.example / compose stub | **Ruled `+psycopg`** (ADR-002's recorded driver; one dependency serves async engine + Alembic sync path); all three sites now agree |
| S-2 missing grace var | .env.example | **Added** `SUNIL_APPROVAL_CONSUME_GRACE_HOURS=1` with C4 §1 rationale comment |
| S-3 turn deadline 40 vs 120 | ARCH §5 / .env.example / compose stub | **Ruled 40** (M1 ~6 s live turn, 30 s p95 target + headroom; fail-closed deadlines must be hittable in dev); all three sites now agree |
| S-4 dev defaults undocumented | ARCH §5 + .env.example comments | **Documented, no behaviour change** — dev-up generates `SUNIL_SERVICE_TOKEN` (lane ON in generated dev env; absent = lane OFF fail-closed); `SUNIL_MEMORY_PROVIDER` runs `fake` until Stream C, `mem0` is the committed end-state value |
| S-5 Get-Random hint | .env.example | **Fixed** — points to dev-up's CSPRNG generators; manual hint now `RandomNumberGenerator`/`openssl rand`; Get-Random explicitly banned as seeded PRNG |

QA follow-ups this round creates (owner: qa_engineer, branch `task/P0-fakes`): rebuild
`FakeMemoryProvider.write` on the v1.1.0 signature (delete `current_scope`/`write_in`/
`DEFAULT_SCOPE`-as-state), migrate the C3 suite's `write_in(scope, …)` calls to
`write(…, scope=…, audit_event_id=…)`, replace `test_c3_write_signature_is_the_frozen_one` with
contract test 7's v1.1.0 pin, and align `decide`'s docstring to C4 §6.2's now-normative return
shape (code already matches). Residual for the platform owner when the compose api stub activates:
the stub's environment block does not yet pass `SUNIL_APPROVAL_CONSUME_GRACE_HOURS` (app default 1
applies; outside this round's permitted stub edits, which were the S-1/S-3 values only).

C4 §6's clock note (QA should-fix: `consume` reads time from inside — injected clock in the fake,
database clock in the real service) is endorsed as-is; it needed no contract text because §6
already specifies the injectable clock.

## Backend fakes-review round (2026-09-10, branch `task/P0-c3-scope`, continued)

Adjudication of three findings from the backend engineer's independent review of the fakes build
(PASS-with-conditions; he built a probe ToolManager against the interfaces to surface them — full
review in the DM's record).

| Finding | Where | Disposition |
|---|---|---|
| F3 — the Tool Manager cannot populate `ParkRequest.continuation`/`summary` from its own frozen inputs; the probe parked `continuation={}` + a synthesised summary (a never-resumable approval) and the suite passed because C1 test 4 asserted only `args_hash` + trace ids | C1 §2.1 vs C4 §4 | **Fixed — C1 v1.1.0 + C4 v1.1.0.** `execute` gains keyword-only `park_context: ParkContext \| None = None` (`ParkContext` typed in C1 §2.2: non-empty `continuation` + `summary`, 1..500 chars), REQUIRED on every first attempt (`approval is None`; missing → `TypeError` before step 1, no attempt row — caller contract violation, same class as constructing without an audit hook), ignored on continuation calls. The manager stays the single `ParkRequest` composer: the two caller fields are copied verbatim; identity triple / `args_hash` / `params_redacted` / trace ids are manager-computed (one composer, one hasher). C4 §4: provenance paragraph + `Field(min_length=1[, max_length=500])` on both fields; §6 fake retains `self.parked[approval_id]`; new C4 test 8 pins model-level rejection of empty park material. C1 test 4 now REQUIRED to assert `continuation`/`summary` by EQUALITY against the caller's non-empty fixture (a never-resumable park can no longer pass); new C1 test 8 pins the precondition; tests 1/5/7 reworded. **Rejected alternative:** orchestrator-composed `ParkRequest` + narrowed park hook — forks the chokepoint QA B3 un-forked (a second `args_hash` hasher outside the manager; validated params escaping the pipeline pre-authorisation) and opens a crash window between `execute` returning `approval_required` and an external park, violating C4 §1's park-transaction-before-return restart safety |
| F4 — `ToolResultMeta.adapter_kind: AdapterKind` non-optional, but the step-1 unknown-tool exit has no adapter (probe wrote `adapter_kind=NATIVE`, a lie); disagrees with `ToolCallAttempt.adapter_kind: AdapterKind \| None` | C1 §2 | **Fixed — C1 v1.1.0 (same bump).** `adapter_kind: AdapterKind \| None`, None iff the tool itself was unknown — the exact rule `ToolCallAttempt` already carried, one convention across both types; an unknown OPERATION on a known tool records the resolved adapter's kind. `\| None` over an `UNKNOWN` member: None already models "no adapter resolved", while an enum member would force every exhaustive match over real adapter kinds to carry an impossible-past-step-1 case and would land a fabricated kind on `tool_calls` audit rows as fact. C1 test 1 probes both sides |
| F11 — `CompletionRequest` has no `extra` policy; `CompletionRequest(..., tools=[...])` is silently ignored, so the no-tools property erodes silently at call sites | C2 §2 | **Fixed — C2 v1.0.1.** Normative closed-models rule: ALL §2 request/result models (`ChatMessage`, `CompletionRequest`, `Usage`, `CompletionResult`, `StreamEvent`) set `extra="forbid"` (property normative; shared `_ClosedModel` base the recommended mechanism). All models, not just `CompletionRequest`: `ChatMessage(..., tool_calls=[...])` is the same erosion channel, and result models are built field-by-field so forbid costs nothing and catches typo'd fields. New contract test 7 (`ValidationError` probes). Strengthens the Security verified-sound no-tools shape; nothing on that list weakened |

Version classifications defended in each changelog: C1/C4 MINOR (the frozen park path was
unimplementable as written — the probe proved implementations must fabricate fields; the change
restores the documents' own frozen semantics, per the C3 v1.1.0/F-1 precedent), C2 PATCH (no field
added/changed/removed; the already-declared closed shape becomes mechanically enforced).

### QA migration delta from this round (consolidated; owner: qa_engineer, branch `task/P0-fakes`)

1. `apps/api/sunil/core/tool_framework/base.py` — add `ParkContext` frozen dataclass
   (`continuation: dict`, `summary: str` — C1 §2.2); `ToolResultMeta.adapter_kind` →
   `AdapterKind | None`; `ToolManagerProtocol.execute` gains keyword-only
   `park_context: ParkContext | None = None`.
2. `apps/api/sunil/core/approvals/base.py` — `ParkRequest.summary: str =
   Field(min_length=1, max_length=500)`; `ParkRequest.continuation: dict = Field(min_length=1)`.
3. `apps/api/sunil/providers/base.py` — add `_ClosedModel(BaseModel)` with
   `model_config = ConfigDict(extra="forbid")`; `ChatMessage`/`CompletionRequest`/`Usage`/
   `CompletionResult`/`StreamEvent` inherit it (per-model `model_config` equally conformant —
   the property is normative).
4. `apps/api/tests/fakes/fake_approvals.py` — `FakeApprovalsService` gains
   `self.parked: dict[str, ParkRequest]`; `park()` stores `self.parked[approval_id] = req`.
5. `apps/api/tests/contracts/test_c1_tool_adapter.py` — fixture adds
   `park_ctx = ParkContext(continuation={"plan_id": "plan-1", "cursor": "step_1"},
   summary="fake_tool.write_item: key=demo")` and every first-attempt `execute` passes
   `park_context=park_ctx`; `test_c1_1_unknown_operation` → two calls (unknown tool →
   `meta.adapter_kind is None`; unknown op on `fake_tool` → `AdapterKind.NATIVE`);
   `test_c1_4_ask_user_without_approval_parks` → add the REQUIRED equality assertions on
   `approvals.parked[approval_id].continuation`/`.summary` vs `park_ctx`;
   `test_c1_5_approved_id_executes_once_then_is_spent` → continuation call passes no
   `park_context`; test 7 pairing accounting per `execute` call; new
   `test_c1_8_first_attempt_without_park_context_raises` (TypeError, zero approvals, zero
   attempts).
6. `apps/api/tests/contracts/test_c2_provider.py` — new test 7
   (`CompletionRequest(..., tools=[{"name": "x"}])` and `ChatMessage(role="assistant",
   content="hi", tool_calls=[])` each raise `pydantic.ValidationError`); the existing model-level
   no-tools test may remain but no longer stands alone.
7. `apps/api/tests/contracts/test_c4_approvals.py` — new test 8 (`ParkRequest(...,
   continuation={})` and `ParkRequest(..., summary="")` each raise `pydantic.ValidationError`);
   verify existing park fixtures already supply non-empty `summary`/`continuation` (any empty
   fixture now fails validation by design).

Out of scope for QA: the concrete `ToolManager` pipeline in `core/tool_framework/manager.py`
implementing the `park_context` precondition and the verbatim-copy composition is production code
owned by the implementing stream (C1 §2.1 module-placement rule); the backend engineer's probe
manager is his own artefact.
