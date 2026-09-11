# Task — S-spine · V2 core spine (app factory, audit spine, governed turn)

Owner (typeKey): backend_engineer · Status: in-progress
**File ownership** (paths only this task may touch, for parallel lanes):
`apps/api/sunil/{main,settings,logging,redaction}.py`, `apps/api/sunil/db/**`,
`apps/api/sunil/core/{audit,trace,conversations,orchestrator,tasks,registry,agent_framework}/**`,
`apps/api/sunil/core/memory/service.py`, `apps/api/sunil/agents/**`,
`apps/api/sunil/api/**` (deps, middleware, schemas, errors, wiring, routes/{auth,health,chat}.py),
`config/{agents,projects}.yaml`, `apps/api/pyproject.toml`,
`apps/api/tests/{unit,integration}/**`.

NOT this task: `core/tool_framework/manager.py`, `tools/**`, `config/tools.yaml`,
`config/permissions.yaml` (Stream A); `providers/*` impls, `core/routing/**`,
`config/models.yaml` (Stream B); `core/approvals/service.py`,
`api/routes/approvals.py` (Stream D); `apps/web` (frontend).

## Static spec (from the Gate-2 lane brief)
**Objective** — build the V2 application spine per `docs/ARCHITECTURE_V2.md`:
FastAPI app factory, settings, Postgres db layer, the audit spine, owner auth,
and `POST /api/v1/chat` running a full governed turn (orchestrator with
validated plans → PM agent → tool call through the C1 ToolManager seam →
analysis → response) with all twelve trace stages in `audit_events`.

**Acceptance criteria**
1. Full suite green, including the contract tests that self-activate as these
   modules land (`plan_models`, `settings`, `api/routes/chat`, `memory/service`).
2. A real turn against the fakes: owner session → validated plan →
   `FakeToolAdapter` call through the permission hook → analysis via
   `FakeProvider` → C5 envelope; twelve stages in `audit_events`.
3. An `ASK_USER`-parked turn returns `outcome=parked` + `ApprovalRef`
   (`FakeApprovalsService`), per the L-001 shape.
4. Alembic migration applies against the Compose postgres.
5. No secrets in code/logs; redaction registry wired for `Authorization`/`Cookie`
   (C5 §3) with its contract test passing.

**Security considerations** — plan-literal rule (C2 §2): the plan schema forbids
templating a later step's params from earlier tool output. Default-deny stays
structural: nothing reaches an adapter except through the C1 chokepoint with a
`ValidatedPlan` (ADR-004 Amendment 1 guard).

## Cross-lane consumers
- `apps/api/sunil/api/schemas.py` (the C5 envelope) → consumed by Stream D
  (renders `parked`), Stream E (n8n triggers), `apps/web`.
- `sunil/api/wiring.py` `Seams`/`SeamUnavailable` → the swap points Streams A/B/C/D
  plug their implementations into (settings-selected; fakes injected in tests).
- `sunil/core/trace/stages.py` `TraceStage` → every stream that emits a stage.
- `sunil/core/orchestrator/plan_models.py` `Plan` → C2 contract test 2; Stream B's
  structured-output lane builds the JSON schema from `plan_schema.build_plan_schema`.
- `sunil/db/models.py` + `alembic` head → Streams C (entity tables) and D
  (approvals table is defined here, service is theirs).

## Progress
- [2026-09-11 | backend_engineer] Read ARCHITECTURE_V2 §§1-8, C1/C2/C4/C5, the
  QA contract suites and the M1 reference (`git show main:…`). Built the spine
  TDD, commit by commit. See Outcome.

## Issues
- `apps/api/tests/contracts/test_c5_chat.py` — should — C5 contract tests 1-7 and 9
  shipped as `pytest.fail("… must be written")` bodies that self-activate the
  moment `sunil.main`/`sunil.api.deps` exist (QA's F5 pattern, by design: the
  harness shape "C5 does NOT fix" was left to the implementer). Discharged here:
  the bodies are now written against the real route, and `StubTurnExecutor` —
  explicitly deferred by `tests/fakes/stub_turn_executor.py` to "the engineer
  building the chat route" — is delivered. Additive only; no QA assertion was
  changed. **Needs QA re-review** since these are contract-suite files.
- `apps/api/tests/contracts/test_c3_memory_provider.py:424` — should — same pattern
  for C3 test 6's service half; body written against `core/memory/service.py`.

## Deviations recorded (Architect sign-off wanted, none blocking)
- **Stage 1 is `request_received`, not M1/ADR-023's `message_received`.** Both V2
  sources name it `request_received` (`ARCHITECTURE_V2.md` §6's audit chain and
  C5 §4's frozen fake trace), and C5 §4 is the wire contract a test asserts
  byte-for-byte. The twelve-stage set does not grow (ADR-023's actual rule);
  only stage 1's name follows the V2 documents.
- **NDJSON**: `Accept: application/x-ndjson` is implemented as a *projection* of
  a completed turn (stage frames, then one token frame per C2 §5 partition
  element, then the single `done` frame). True incremental streaming of the
  analysis call (ADR-028) stays M2 work, as the lane brief permits.
- `core/registry` loads `agents.yaml`/`projects.yaml` only. The tool/permission
  registries are Stream A's files, so the plan validator re-checks tools and
  operations against the **C1 adapter registry** (`ToolCatalogue`), which is
  registry-derived at runtime rather than a second copy of `tools.yaml`.

## Outcome
- Commits: see `git log task/S-spine`. Test evidence in the lane report.
