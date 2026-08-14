# SUNIL M1 — Ordered Build Plan (T1 … T21)

**Author:** Solution Architect, Minions Team 18 · **Status:** revised after the owner's review · **Date:** 2026-08-14
**Milestone:** M1, the `ROADMAP.md` §22 vertical slice. **Build starts 2026-08-14. DUE 2026-08-18.**
**Builds from:** [`ARCHITECTURE_V1.md`](ARCHITECTURE_V1.md) (see its amendment log A-1…A-9) ·
[`decisions/`](decisions/) ADR-000…016 · [`THREAT_MODEL.md`](THREAT_MODEL.md) ·
[`REQUIREMENTS_V1.md`](REQUIREMENTS_V1.md) · [`design/M1_CHAT_SPEC.md`](design/M1_CHAT_SPEC.md) ·
[`design/DESIGN_SYSTEM.md`](design/DESIGN_SYSTEM.md)
**Working model:** [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) — the Delivery Manager's document, in force.
It is **not** duplicated here; §0.1 below only says how the tasks map onto it.

---

## Revision note — what changed and why

The owner reviewed this plan on 2026-08-14 and scored it **7.5/10**: *"Revise the M1 build plan
before execution."* His corrections are applied, not evaluated. The substantive ones:

| # | Correction | Where |
|---|---|---|
| 1 | **The stated critical path was wrong.** `T1→T2→T4→T5→T11→T20` omitted the T8→T10 chain. T6, T8, T9 and T10 are **on** the critical path and were wrongly described as slack | §1, §8 |
| 2 | **No concurrent commits to `main`.** One branch per task, worktrees per lane, merge through review + CI | §0.1 |
| 3 | **Minimal CI now**, gating every merge — new task **T21** | §5, T21 |
| 4 | T2 said "all eleven tables" and then listed twelve. It is **twelve** | T2 |
| 5 | **T12, T13, T17 are pre-classified OPTIONAL / post-M1**, decided now rather than on the day | §9 |
| 6 | The owner's 24-step success test is adopted as the definitive acceptance walkthrough | §10 |
| 7 | The date is settled: **build starts 08-14, due 08-17.** The old "date ambiguity" warning is deleted | header |
| 8 | T11 is **split into T11a / T11b** — my change, to take ~2.5 h off the tail of the critical path | §2 |

**And the headline, stated plainly because the owner asked for plainness, not optimism:
the recalculated critical path is ~27.5 hours of work and review latency against roughly 28
available hours. M1 fits only if nothing goes wrong. §8.4 says what to do about that.**

---

## 0. How to use this

Twenty-one numbered tasks — twenty-two work items, since T11 splits into T11a and T11b — across seven
lanes. A task's **"Owns"** list is exclusive: no other task edits those paths.
That rule still holds — it is what stops two agents editing one file — but it is no longer the
*only* protection, because file ownership never protected repository state.

Lanes: **BE-1** backend core · **BE-2** backend integrations · **BE-3** backend support ·
**FE** frontend · **QA** · **SEC** security · **OPS** devops.

### 0.1 The working model — branches and worktrees

**Nobody commits to `main`.** Read [`GIT_WORKFLOW.md`](GIT_WORKFLOW.md) before your first commit; it
is the authority and this section is only the mapping.

```
task branch  →  tests green  →  CI (T21)  →  QA / Security review  →  controlled merge  →  main
```

| Lane | Worktree | Tasks |
|---|---|---|
| BE-1 | `C:\repo\SUNIL-wt\be-core\` | T1, T2, T4, T5, T11a, T11b |
| BE-2 | `C:\repo\SUNIL-wt\be-integr\` | T3, T6, T8, T10 |
| BE-3 | `C:\repo\SUNIL-wt\be-support\` | T7, T9, then T13/T12 if they are reached |
| FE | `C:\repo\SUNIL-wt\frontend\` | T14, T15, T16 |
| QA | `C:\repo\SUNIL-wt\qa\` | T18, T20 (with BE-1) |
| SEC | `C:\repo\SUNIL-wt\security\` | T19 |
| OPS | `C:\repo\SUNIL-wt\ops\` | T21, T17 |

Branch names are `task/T<n>-<slug>` — e.g. `task/T8-github-tool`, `task/T11a-conversation-gateway`.

**Stacked branches are expected and are how this schedule survives.** A dependent task does not wait
for its dependency to reach `main`. It branches from the dependency's branch the moment that branch
is *feature-complete and green*, and rebases onto `main` after the dependency merges:

```bash
git fetch origin
git worktree add ../SUNIL-wt/be-integr -b task/T10-agents origin/task/T8-github-tool   # stack
# ... after T8 merges:
git rebase --onto origin/main origin/task/T8-github-tool
```

Two rules keep that safe, and they are not optional:
1. **Merge order follows dependency order.** A stacked branch is never merged before its base.
2. **Announce "green" in the Delivery Manager's thread**, naming the branch and the commit, the
   moment a dependency is consumable. A dependent lane that does not know cannot start.

Everything else — no self-merges, no weakened tests, rebase not merge, push often — is in
`GIT_WORKFLOW.md`.

### 0.2 Rules for everyone building this

1. **Escalate, do not invent.** If this plan or the architecture does not answer a question, ask the
   Architect through the Delivery Manager. You will get an exact config name and a default, not a
   direction. Inventing a mechanism that contradicts a document is how M1 slips.
2. **The contract in §6 is frozen.** Changing an endpoint, a field name or a failure kind requires an
   Architect ruling, because the frontend and QA are building against it *before* the backend exists.
3. **Do not name a library that is not in `ARCHITECTURE_V1.md` §14.3.** Every entry there was checked
   to exist for Python 3.13 / Node 24 on 2026-08-14. Adding one is an escalation.
4. **`python`, never `python3`** on this machine (`ENVIRONMENT.md` §1 — the Store stub).
5. **Never bind port 4317.** It is the Minions Portal.
6. **Scoped `git add <path>` only, never `git add -A`** — now for hygiene rather than for safety:
   your branch is yours, but a stray `.venv/` or `var/sunil.db` in a diff wastes a review cycle.
7. **Definition of done, every task:** code + its own unit tests green + `ruff` clean + the named
   requirements demonstrably satisfied + **CI green** + reviewed by someone who did not write it +
   merged by the Delivery Manager. Pushing is not done.
8. **Logical LLM stages are not provider calls (A-2).** Anywhere you count, log, price or assert on
   model usage, count **provider attempts** — one `llm_calls` row each.

---

## 1. Dependency graph and the real critical path

### 1.1 Dependencies

```
 T1 foundation ─┬─ T2 data layer ─┬──────────── T4 trace spine ──┬── T5 API skeleton ── T11a gateway ─┐
                │                 │                              │                                    │
                │                 └──────────────┐               ├── T6 router ──┬── T9 plan validation┤
                └─ T3 registries ─┬── T7 perms ──┼── T8 tools ───┘               │                    │
                                  │              │        │                      │                    │
                                  └──────────────┘        └──── T10 agents ◀─────┘                    │
                                                                     │                                │
                                                                     └────── T11b orchestrator turn ◀─┘
                                                                                    │
                                                        T12 SSE (OPT) ◀─────────────┤
                                                        T13 trace API (OPT) ◀───────┘
 T14 web scaffold ── T15 chat components ── T16 API client + useTurn ──┐
 T17 dev topology (OPT, OPS)                                           ├─▶ T20 integration + runbook
 T18 QA red exit tests (starts hour 0, against §6)                     │
 T19 security review + boundaries + injection ─────────────────────────┘
 T21 CI (OPS) — merges with T1; every task above passes through it
```

Explicitly, as the owner's review §4 sets them out:

| Task | Depends on |
|---|---|
| T4 | T1, T2 |
| T5 | T1, T2, T4 |
| T6 | T3, T4 *(T1 for the trace **interface** — see the note below)* |
| T7 | T3 |
| T8 | **T2, T3, T4, T7** |
| T9 | **T3, T6** |
| T10 | **T3, T6, T8, T9** |
| T11a | T2, T4, T5 |
| T11b | **T9, T10, T11a** |
| T20 | everything |

### 1.2 The three branches, and which one binds

The owner's review traces three genuine branches to T20. Costed with the estimates in §8.1:

| Branch | Chain | Work hours |
|---|---|---|
| **A** | T1 → T3 → T6 → T9 → T10 → T11b → T20 | 2 + 3 + 4 + 3.5 + 3 + 3.5 + 3 = **22.0** |
| **B** | T1 → T2 → T4 → T8 → T10 → T11b → T20 | 2 + 4 + 3 + 4 + 3 + 3.5 + 3 = **22.5** ← **binds** |
| **C** | T1 → T2 → T4 → T5 → T11a → T11b → T20 | 2 + 4 + 3 + 3 + 3 + 3.5 + 3 = **21.5** |

**The critical path is Branch B: T1 → T2 → T4 → T8 → T10 → T11b → T20.**

The previously stated path (`T1→T2→T4→T5→T11→T20`) is Branch C with the old un-split T11 — it was
arithmetically similar and structurally wrong, because it treated the work that *feeds* T11 as
slack. **T6, T8, T9 and T10 are on the critical path. None of them is parallel-lane filler, and
none of them is a descope candidate** — between them they are the model router, the tool, the plan
validator and the agent, which is to say: the vertical slice.

All three branches converge on T10 → T11b → T20, so the tail is common and irreducible; the
difference between branches is under an hour. Treat all three as critical and none as slack.

> **Note on T6's dependency, and why it is worth 2 hours.** T6 and T8 nominally wait for T4's
> emitter. To stop that serialising the two heaviest backend tasks behind the trace spine, **T1 now
> owns the trace *interface*** — `TraceStage` (the twelve names) and the `TraceContext` protocol with
> a null implementation — while T4 keeps the emitter, the three sinks, the audit writer and
> redaction. T6 and T8 are then written and unit-tested against a fake trace context from hour 2, and
> only their *integration* tests need T4 merged. This is a real change to T1's and T4's ownership,
> made deliberately: it is the cheapest two hours on the critical path.

---

## 2. Backend core lane (BE-1)

### T1 — Backend foundation, tooling, and the trace interface
**Deps:** none. **Blocks:** everything backend. **Merges with T21 (CI).**
**Owns:** `apps/api/pyproject.toml`, `apps/api/sunil/__init__.py`, `apps/api/sunil/settings.py`,
`apps/api/sunil/logging.py`, `apps/api/sunil/main.py` *(created here; extended by T5 — same lane)*,
**`apps/api/sunil/core/trace/stages.py`** and the `TraceContext` **protocol** in
`apps/api/sunil/core/trace/context.py`, `apps/api/tests/unit/test_settings.py`,
`.env.example`, `scripts/dev-api.ps1`, `apps/api/README.md`, one appended line in `.gitignore` (`var/`).
**Build:** venv + `pip install -e ".[dev]"`; `pydantic-settings` `Settings` with every variable in
`ARCHITECTURE_V1.md` §14.4 — **including the three new ones, `SUNIL_CONFIG_DIR`,
`SUNIL_TURN_DEADLINE_S` (default 40) and `SUNIL_PROGRESS_EVENTS` (default `false`)** — secrets as
`SecretStr`; `structlog` JSON renderer with `contextvars`, uvicorn's loggers routed into the same
chain; `create_app()` returning a bare `FastAPI`; ruff + pytest config in `pyproject.toml`;
`TraceStage` StrEnum with exactly the twelve NFR-020 names and a `TraceContext` Protocol +
`NullTraceContext` so BE-2 can build against it from hour 2.
**Satisfies:** FR-005, FR-008. **Exit tests enabled:** none directly (unblocks all).
**Watch:** `.env.example` carries **placeholders only** — a real value here is an ET-10 failure.
`test_settings.py` exists so T21's `pytest` job cannot pass by collecting zero tests (exit code 5).

### T2 — Data layer, models, migration `0001`
**Deps:** T1.
**Owns:** `apps/api/alembic.ini`, `apps/api/migrations/**`, `apps/api/sunil/db/base.py`,
`apps/api/sunil/db/models.py`, `apps/api/sunil/db/session.py`, `apps/api/sunil/db/capture.py`,
`scripts/seed-owner.py`.
**Build:** all **twelve** tables from `ARCHITECTURE_V1.md` §7.3 — `users, conversations, messages,
workflows, tasks, task_status_events, plans, tool_calls, approvals, memories, llm_calls,
audit_events`. *(The previous revision of this line said "eleven" and listed twelve. Twelve.)*
Plus **§7.3.1's four capture columns** — `capture_policy`, `sensitivity`, `retention_class`,
`training_eligible` — on `messages`, `plans`, `llm_calls`, `tool_calls`, `memories`, and **not** on
`audit_events`; `db/capture.py` holds the `resolve_capture()` resolver and the writer behaviour that
nulls content under `none` / `metadata_only` (ADR-014).
**Obey §7.2's portability rules exactly** (text UUIDs, `sa.JSON().with_variant(JSONB, "postgresql")`,
UTC datetimes, `BigInteger` micro-USD for money, no native enums, no server defaults). Async engine +
`async_sessionmaker`; async `env.py`; `downgrade()` implemented; startup asserts
`alembic_version == head`.
**Satisfies:** FR-002, FR-021, FR-063, FR-103, FR-144. **Exit tests:** ET-2, ET-4, ET-9 (storage side).
**Announce early:** post "models frozen" in the DM thread the moment `db/models.py` is complete —
T4 and T8 both wait on those classes, not on the migration.
**Watch:** `Numeric` on SQLite is lossy and warns — use micro-USD integers. Autogenerate is a draft,
not a commit (ADR-002).

### T4 — Observability spine: trace emitter, audit, redaction
**Deps:** T1, T2. **Blocks:** T5, T6, T8, T11a. **On the critical path.**
**Owns:** `apps/api/sunil/core/trace/{context.py (implementation),emitter.py}`,
`apps/api/sunil/core/audit/writer.py`, `apps/api/sunil/redaction.py`.
**Touches (one line, same lane):** `sunil/logging.py` — register the redaction processor.
**Build:** the concrete `TraceContext` (holding `request_id`, `user_id`, `conversation_id`,
`started_at`, `seq`, **and the §5.3 turn deadline**); **one** `emit()` writing to three sinks (log
line, `audit_events` row, trace bus — the bus is a no-op stub unless T12 lands).
`redaction.register()` + `redaction.scrub()` per ADR-006, wired as a structlog processor **and**
called before every `llm_calls` / `tool_calls` / `audit_events` insert.
**Each of the twelve stages is emitted at most once per turn** (§3.4): retries go in `detail`
(`provider_attempts`, `plan_attempts`), never in extra stage rows.
**Satisfies:** FR-008, FR-067, NFR-001/005/006/020. **Exit tests:** **ET-6, ET-10**.
**Watch:** untrusted content goes in a *field*, never interpolated into a log message string (T-32).

### T5 — API skeleton: middleware, auth, health
**Deps:** T1, T2, T4.
**Owns:** `apps/api/sunil/api/{deps.py,schemas.py,middleware.py}`,
`apps/api/sunil/api/routes/{auth.py,health.py}`.
**Extends (same lane):** `sunil/main.py` — the middleware list and router registration.
**Build:** middleware via the **explicit constructor list**, CORS outermost
(`ARCHITECTURE_V1.md` §3.3); `RequestContextMiddleware` accepting/validating `X-Request-Id` as UUID4,
binding it to contextvars **and starting the turn deadline clock**; `SessionMiddleware`;
`require_owner_session` (401) and `require_client_header` (403, checks `X-SUNIL-Client` and
`Origin`); login with `hashlib.scrypt` and a 5-failure/60 s throttle; `GET /api/v1/health` returning
liveness + alembic revision.
**Satisfies:** FR-001, FR-004, FR-007, FR-026. **Exit tests:** prerequisite for all.
**Watch:** `allow_origins` must be the explicit `WEB_ORIGIN`, never `"*"` — a wildcard with
`allow_credentials=True` is rejected by every browser (T-07).

### T11a — Conversation gateway, task/workflow lifecycle, chat envelope
**Deps:** T2, T4, T5. **New — the front half of the old T11.**
**Owns:** `apps/api/sunil/core/conversations/**`, `apps/api/sunil/core/tasks/**`,
`apps/api/sunil/core/workflows/**`, `apps/api/sunil/core/memory/short_term.py`,
`apps/api/sunil/api/routes/chat.py` *(new file in T5's directory, same lane)*.
**Build:** create/load conversation and persist both messages; Task + Workflow +
`task_status_events`; short-term memory read/write with `source_request_id`; **the entire §6 response
envelope** including `outcome`, the discriminated `failure`, `trace[]` and `usage`; stages 1, 2, 3
and 12. The turn executor is behind a Protocol with a stub implementation returning
`failure.kind = plan_rejected`, so the endpoint is real, testable and integrable **before** T11b
exists — which is the entire point of the split.
**Satisfies:** FR-021, FR-063, FR-064, FR-065, FR-066, FR-140. **Exit tests:** ET-2 (Task+Workflow),
part of ET-6.
**Watch:** stage 12 fires on every path, including the stub failure (ET-8's shape).

### T11b — Orchestrator turn: plan → agent → outcome
**Deps:** T9, T10, T11a. **The integration task, and the tail of all three branches.**
**Owns:** `apps/api/sunil/core/orchestrator/turn.py`.
**Build:** stages 4–11 of `ARCHITECTURE_V1.md` §3.4; bounded plan retry (3 logical attempts, prior
validation errors fed back as corrective context); agent invocation through the runner; **the turn
deadline check before every provider attempt** (§5.3); the four failure outcomes of §11.3 returned as
HTTP 200 with a discriminated `failure.kind`; `unknown_project` returning `known_projects` from the
registry. **No final-response LLM call (ADR-015)** — `AgentResult.summary` is persisted as the
assistant message and stage 12 is emitted by this code.
**Satisfies:** FR-020, FR-022, FR-060–062, FR-067, FR-107, NFR-060/071. **Exit tests:** ET-1, ET-3,
ET-5, ET-7, ET-8, ET-11.
**Watch:** a failed turn must still emit stage 12 (ET-8). The assistant message is the agent's prose,
never raw tool JSON (ET-5).

### T12 — SSE progress channel · **OPTIONAL / POST-M1** (§9)
**Deps:** T4, T11b. **Lane:** BE-3 if it is reached at all.
**Owns:** `apps/api/sunil/core/trace/bus.py`, `apps/api/sunil/api/routes/events.py`.
**Touches (one line):** `core/trace/emitter.py` — publish to the bus.
**Build:** `TraceBus` per ADR-009 — owning `user_id`, 64-event replay buffer, subscriber queues,
5-minute TTL, first-claim-wins ownership with 403 on mismatch; `StreamingResponse` with
`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`; `event: stage` frames, a
terminal `event: done`, a `: ping` heartbeat every 15 s, close on terminal or 120 s. Gated by
`SUNIL_PROGRESS_EVENTS`, **which ships `false`.**
**Exit tests:** none — it is cosmetic by construction. T16's fallback stepper carries the UI without it.

---

## 3. Backend integrations lane (BE-2)

### T3 — Configuration registries
**Deps:** T1. **On the critical path (Branch A).**
**Owns:** `config/agents.yaml`, `config/permissions.yaml`, `config/projects.yaml`,
`config/models.yaml`, `config/tools.yaml`, **`config/capture.yaml`**,
`apps/api/sunil/core/registry/**`.
**Build:** the exact file contents in `ARCHITECTURE_V1.md` §9.2, §10.2 and §4.4 (including the pinned
price table and `pricing_version`), plus `capture.yaml`'s defaults per content kind with per-project
override (ADR-014, §13.2); typed loaders reading from **`SUNIL_CONFIG_DIR`** (ADR-016);
**startup cross-validation** — every agent in `permissions.yaml` exists in `agents.yaml`, every
tool/operation referenced exists in `tools.yaml`, every project referenced in `capture.yaml` exists
in `projects.yaml` — refusing to boot on mismatch.
**Satisfies:** FR-080, FR-084, FR-100, FR-107. **Exit tests:** ET-11 (the project registry half).
**Watch:** the target repository is `codely-isuru/easy_clean_workforce` and it lives **only** in
`config/projects.yaml` (ADR-000 Q7). Hard-coding it anywhere is a review failure.

### T6 — Provider interface and Model Router
**Deps:** T3 + T1's trace interface (integration tests need T4). **On the critical path.**
**Owns:** `apps/api/sunil/providers/{base.py,anthropic.py,registry.py}`,
`apps/api/sunil/core/routing/{router.py,capabilities.py,pricing.py,retry.py}`.
**Build:** the protocol and dataclasses of `ARCHITECTURE_V1.md` §4.2 (`LLMPurpose` includes
`FINAL_RESPONSE`, which **no M1 code path uses** — ADR-015); the Anthropic adapter against the
verified surface in §4.3 — `AsyncAnthropic`, `max_retries=0`, `output_config={"format":
{"type":"json_schema","schema":…}}`, `usage.input_tokens`/`output_tokens`, `_request_id`, and the
exception mapping to `ProviderTransientError`/`ProviderPermanentError`; router capability lookup,
3-attempt backoff with jitter, **a turn-deadline check before each attempt** (§5.3 — an attempt whose
timeout exceeds the remaining budget is not started), one `llm_calls` row **per provider attempt**,
cost in micro-USD from the pinned table.
**Satisfies:** FR-040/041/042/045/046, NFR-010/030/070. **Exit tests:** ET-8, **ET-9**.
**Watch:** `sunil/providers/` is the **only** package permitted to `import anthropic` (FR-040's own
acceptance criterion). T19 tests it and T21 runs that test on every merge.

### T8 — Tool framework and the GitHub adapter
**Deps:** T2, T3, T4, T7. **On the critical path — Branch B, the binding one.**
**Owns:** `apps/api/sunil/core/tool_framework/{base.py,manager.py}`,
`apps/api/sunil/tools/github/{adapter.py,projection.py}`.
**Build:** `ToolManager.execute()` in the exact order of `ARCHITECTURE_V1.md` §9.3, **including new
step 0**: reject any call not carrying `ExecutionMetadata` (`validated_plan_id`, `request_id`,
`task_id`, `agent_id`) and run `require_validated_plan()` — ADR-004 Amendment 1. All four fields are
written onto the `tool_calls` row. Pydantic `params_model` per operation; `tool_calls` row written
before the adapter is reached; every adapter exception normalised, never propagated.
GitHub: three concurrent `httpx` GETs (commits, open PRs, open issues), `Authorization: Bearer`,
`Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`, 15 s timeout;
**`owner`/`repo` resolved from `config/projects.yaml`, never from the plan**; the allow-listed,
length-capped projection of §9.4 control 3 with issue and PR **bodies excluded**.
`projection.py` is a **security component** — success-test step 13 (§10) is its job.
**Satisfies:** FR-101–105, NFR-002/008/011/012. **Exit tests:** **ET-4**, and ET-1's data half.
**Watch:** GitHub's `/issues` endpoint **also returns pull requests** — filter items carrying a
`pull_request` key or every PR is counted twice.

### T10 — Agent framework and the Project Manager agent
**Deps:** T3, T6, T8, T9. **On the critical path — all three branches pass through it.**
**Owns:** `apps/api/sunil/core/agent_framework/{base.py,runner.py}`,
`apps/api/sunil/agents/project_manager/agent.py`.
**Build:** `AgentContext` exposing exactly `call_tool`, `ask_model`, `memory`, `trace` — **no DB
session, no HTTP client, no secrets** (NFR-007); the runner running `require_validated_plan()` on
entry (guard site 2), minting the `ExecutionMetadata` the agent cannot mint itself, and rejecting a
tool absent from the agent's own config *before* the Tool Manager (FR-082). The PM agent does
ADR-000 Q2 and nothing more: resolve project → one read-only call → LLM summary in 2–4 sentences →
return. **That summary is the user-facing answer (ADR-015)** — it is not an intermediate artefact,
and the agent's `instructions` in `config/agents.yaml` are therefore user-facing copy. The analysis
call passes **no `tools` parameter** and wraps the projection in `<untrusted_tool_result>` with the
delimiter escaped (THREAT_MODEL §5.1 controls 1 and 4).
**Satisfies:** FR-080/081/082/084, NFR-007/011/012. **Exit tests:** ET-3, **ET-5**.
**Watch:** the summary must reference only data present in the tool result. "Never claim anything the
tool result does not show" is in the agent's instructions for a reason, and it is now the last line
of defence before the owner reads it (ET-1).

### T13 — Trace read endpoint · **OPTIONAL / POST-M1** (§9)
**Deps:** T4, T11b. **Lane:** BE-3 if reached.
**Owns:** `apps/api/sunil/api/routes/trace.py`.
**Build:** `GET /api/v1/trace/{request_id}` reassembling `audit_events` + `llm_calls` + `tool_calls`
summaries. This is the NFR-050 verification query and the seed of M8's NFR-021 view.
**Why it is safely optional:** the trace already ships inside the chat response (§6), so
`TraceDisclosure` works without it. Only the debugging endpoint is lost.

---

## 3.1 Backend support lane (BE-3)

### T7 — Permission engine
**Deps:** T3.
**Owns:** `apps/api/sunil/core/permissions/engine.py`.
**Build:** the `decide()` function of `ARCHITECTURE_V1.md` §9.2 — three-valued `Decision`, structural
default-deny (the missing-key branch returns DENY), a `PermissionResult` carrying `reason` and
`source`.
**Satisfies:** FR-120, FR-121, NFR-007. **Exit tests:** **ET-4**.
**Watch:** ship `test_empty_permission_config_denies_everything` — it is what makes "default-deny"
a fact rather than a description.

### T9 — Plan schema, models, validator, `ValidatedPlan`
**Deps:** T3, T6. **On the critical path (Branch A). The highest-value task in M1.**
**Owns:** `apps/api/sunil/core/orchestrator/{plan_schema.py,plan_models.py,plan_validator.py,guards.py}`.
**Build:** all five layers of ADR-004 exactly — runtime schema built from the registries with `enum`
whitelists and the `__unknown__` / `none` sentinels; `PlanDraft` with `extra="forbid"` and the
`0.0 ≤ confidence ≤ 1.0` check; `validate_plan()` re-checking against live registries **and**
`permissions.yaml`; `ValidatedPlan` constructible only with the module-private token.
**Plus ADR-004 Amendment 1:** `guards.py` with `InvalidPlanExecution` and `require_validated_plan()`,
and the `ExecutionMetadata` frozen dataclass. The guard is called at three sites (here, T10's runner,
T8's manager) — **it is not a security boundary that the type alone provides, and the ADR now says
so; the guard is what makes it enforceable.**
**Satisfies:** FR-060, FR-061, FR-062, NFR-040/041. **Exit tests:** **ET-7**, and ET-11's mechanism.
**Watch:** the schema must stay inside the verified `output_config` feature envelope
(`ARCHITECTURE_V1.md` §4.3) — **no `minimum`/`maximum`, no `minLength`, no nullable union types.**
Ship all **nine** tests from §6.3; deleting one deletes the control.

---

## 4. Frontend lane (FE)

### T14 — Web scaffold and the token contract
**Deps:** none — **starts at hour 0.**
**Owns:** `apps/web/{package.json,pnpm-lock.yaml,next.config.ts,tsconfig.json,tailwind.config.ts,postcss.config.js}`,
`apps/web/src/app/{layout.tsx,globals.css}`, `apps/web/src/styles/**`.
**Build:** `pnpm create next-app` **without Tailwind**, then `pnpm add -D tailwindcss@3.4.19 postcss
autoprefixer` (ADR-012 — the scaffold now defaults to v4 and the design system is v3 syntax). Paste
`DESIGN_SYSTEM.md` §1's `theme.extend` block **verbatim**; wire the three font stacks; implement the
§7 accessibility floor (focus ring, reduced motion, rem sizing). Add `typecheck` and `build` scripts
— **T21's frontend CI job runs exactly those two.**
**Watch:** `apps/web` gets its **own** lockfile, and it must be committed (CI runs
`pnpm install --frozen-lockfile`). Do not `npm install` at the repo root — a stale 1.1 GB
`node_modules/` from the retired build is still there (`ENVIRONMENT.md` §2).

### T15 — Chat components
**Deps:** T14.
**Owns:** `apps/web/src/components/chat/**` — one file per `M1_CHAT_SPEC.md` §7 component:
`ChatShell, TopBar, MessageList, MessageBubble, AssistantMessage, TraceDisclosure, WorkIndicator,
ErrorCard, Composer, SuggestionChips, JumpToBottomPill, StatusDot`.
**Build:** presentational only, driven by props — no data fetching. All four `ErrorCard` variants with
the Designer's **final copy, verbatim, not paraphrased** (§5.6–5.9). Components stay chrome-agnostic
(`DASHBOARD_DIRECTION.md` §2).
**Satisfies:** FR-003.
**Watch:** the markdown renderer must **not** enable raw HTML (THREAT_MODEL T-02). Desktop-only
Enter-to-send (§1.2). Reduced-motion handling on `WorkIndicator`.

### T16 — API client, auth screen, `useTurn`
**Deps:** T14, T15. **Contract only** — builds against §6 with a local stub, not against a running
backend. Integration is T20.
**Owns:** `apps/web/src/lib/{api.ts,phases.ts,copy.ts,useTurn.ts}`,
`apps/web/src/app/(chat)/page.tsx`, `apps/web/src/app/login/page.tsx`.
**Build:** `fetch` with `credentials:"include"`, `X-SUNIL-Client: web`, client-generated
`X-Request-Id`; `EventSource` with `withCredentials`; the 12→4 phase map and all human labels
(**the API sends enums only**); 400 ms minimum phase display, 20 s reassurance line, 45 s client
timeout; `AbortController` cancel with the Designer's §6 copy **unchanged, including the "even if I
finish it in the background" clause** (ADR-010); and the **fallback stepper**, which is now the
**primary** path, because `SUNIL_PROGRESS_EVENTS` ships `false` and T12 is optional (§9).
**Satisfies:** FR-003, FR-007 (client side). **Exit tests:** ET-1's UI half, ET-11's UI half.
**Watch:** `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` — **`localhost`, never `127.0.0.1`**, or
the session cookie is silently withheld (ADR-008). Stages 11 and 12 now arrive back to back
(ADR-015); the 400 ms minimum-display rule is what keeps "Finishing" visible, so do not remove it.

---

## 5. OPS, QA and Security lanes

### T21 — Minimal CI · **NEW, and it gates every merge**
**Deps:** T1 (backend job), T14 (frontend job). **Lane: OPS. Merges with or immediately after T1.**
**Owns:** `.github/workflows/ci.yml`, `docs/CI.md` (what each job does and how to reproduce it locally).
**Build:** three jobs on push and pull request, `ubuntu-latest`:

| Job | Runs |
|---|---|
| `backend` | Python 3.13 · `pip install -e ".[dev]"` · `ruff check .` · `ruff format --check .` · `pytest -q` |
| `frontend` | Node 24 + pnpm · `pnpm install --frozen-lockfile` · `pnpm typecheck` · `pnpm build` |
| `security` | `pytest apps/api/tests/security -q` — the DC-10 import-boundary tests and the critical security tests, run as their own job so a failure is legible at a glance |

**Constraints that matter:**
- **CI runs with no secrets.** No `ANTHROPIC_API_KEY`, no `GITHUB_TOKEN` in any workflow. The suite
  runs against `FakeProvider` and a local SQLite file. Any test needing a real credential is marked
  `@pytest.mark.live` and deselected in CI (`-m "not live"`). A CI job that needs a secret to pass is
  a CI job that will leak one.
- **Empty is not green.** `pytest` exits 5 when it collects nothing; the workflow treats 5 as
  failure. T1 ships `test_settings.py` so this is never hit by accident.
- The frontend job is added the moment T14 merges; until then it is `if: hashFiles('apps/web/package.json') != ''`.
- **Deployment CI stays deferred** (FR-009, M11). This is validation only. So are dependency CVE and
  secret scanning (DC-9).

**Bootstrapping, because it is circular otherwise:** merges are gated on CI, and CI cannot exist
before the first merge. T21 and T1 are reviewed together and merged in that order — T21 first with
the backend job, T1 immediately after as the first branch the gate is applied to.

### T17 — Local dev topology (OPS) · **OPTIONAL / POST-M1** (§9)
**Deps:** T1, T2. **Independent of the backend's progress.**
**Owns:** `infra/docker/{docker-compose.yml,Dockerfile.api}`, `scripts/{dev-check.ps1,dev-web.ps1}`,
`docs/RUNBOOK.md`.
**Build:** compose per `ARCHITECTURE_V1.md` §14.2 — `pgvector/pgvector:pg17`, Redis behind a
non-default `queue` profile, api behind a `full` profile, **and `./config:/app/config:ro` with
`Dockerfile.api` copying no config at all** (ADR-016). **`dev-check.ps1` is the valuable part:**
probe `http://localhost:8000/api/v1/health`, assert `WEB_ORIGIN` and `NEXT_PUBLIC_API_BASE_URL` both
use `localhost` and not `127.0.0.1`, assert nothing is bound to 4317 by us, and print the exact
remedy on failure.
**If T17 is deferred, `dev-check.ps1` is not** — pull that one script forward into T1 (30 minutes).
The compose file is what is optional; the preflight script pays for itself on day one.
**Watch:** compose must not be a prerequisite for anything in M1 (ADR-001/005/013). Docker Desktop is
now running (server 29.7.2, Compose v5.3.1), which makes the no-Docker path a **contingency**, not
the plan — it does not put Docker back on the critical path.

### T18 — QA red exit-test harness
**Deps:** the §6 contract only. **Starts hour 0, red.**
**Owns:** `apps/api/tests/{integration,exit}/**`, `apps/api/tests/conftest.py`, fixtures and the fake
provider.
**Build:** ET-1 … ET-11 as executable tests, red first; a `FakeProvider` implementing `LLMProvider`
for deterministic and fault-injected runs (malformed plan for ET-7; transient-then-success for ET-8;
**a transient-forever mode for the §5.3 turn-deadline path**); DB assertions for ET-2/3/4/9; the
twelve-stage ordering **and uniqueness** query for ET-6; the unknown-project path for ET-11.
**Two assumptions to build in, both from A-2/ADR-015:** a turn's `llm_calls` rows are one **per
provider attempt** (never a hard-coded count), and their `purpose` values are `plan` and `analysis`
only. An assertion of "exactly three LLM calls" would have been wrong even before ADR-015, because
one retry breaks it.
**Split of ownership:** backend engineers own `apps/api/tests/unit/**` for their own modules; QA owns
`integration/` and `exit/` exclusively; Security owns `security/`. No file is written by two lanes.

### T19 — Security review, import boundaries, injection tests (SEC)
**Deps:** T8, T11b for the injection test; the boundary tests can be written from hour 0.
**Owns:** `apps/api/tests/security/**`.
**Build:** **DC-10's import-boundary tests as AST-walking tests, not lint config** (so no lane has to
edit `pyproject.toml`): only `sunil/providers/**` may import `anthropic`; only
`sunil/core/tool_framework/**` may import `sunil.tools.*`; `sunil/core/**` may not import `sunil.api`.
Plus the ET-10 secret-scan tests; the T-15 injection test (a commit message containing an embedded
instruction); **the step-13 sanitisation tests — `test_tool_result_projection_excludes_issue_bodies`,
`test_projection_escapes_the_untrusted_delimiter`,
`test_no_unprojected_github_payload_reaches_a_prompt`**; the T-16 test that repo coordinates never
originate in a plan; **the ADR-004 Amendment 1 guard tests** (`test_run_agent_rejects_a_non_validated_plan`,
`test_tool_manager_requires_execution_metadata`, `test_tool_call_row_carries_validated_plan_id`);
and **the ADR-014 capture tests** (`test_capture_policy_none_stores_no_content`,
`test_capture_policy_metadata_only_stores_no_content`,
`test_audit_events_are_never_suppressed_by_capture_policy`). Then a design/code review against
`THREAT_MODEL.md`.
**Satisfies:** NFR-001/002/005/007/011/012. **Exit tests:** **ET-10**.

### T20 — Integration, latency measurement, runbook
**Deps:** all. **Lane: BE-1 + QA together.**
**Owns:** `README.md` (M1 run instructions), `apps/api/tests/exit/test_latency.py`, and the final
`docs/STATUS.md` update **by the Delivery Manager, not by an engineer**.
**Build:** run the full stack; make ET-1 … ET-11 green; walk §10's 24 steps; confirm the frontend
renders the fallback progress path (and the SSE path only if T12 landed).
**Latency, measured honestly (A-2, §5.2):** five timed runs cannot produce a p95 — five samples give
a median and a max. Report **median, max, and the provider-attempt count for each run** against the
30 s target, and state it as an indicative measurement. Do not write "p95 = X" next to n=5. Debt D-12
records that a real p95 needs M11's sample size.

---

## 6. The frozen contract (build against this, not against each other)

Frontend and QA start before the backend exists. **These names are fixed; changing one is an
Architect escalation.**

```
POST /api/v1/auth/login      {username, password}                    → 200 {user:{id,name}} + Set-Cookie
POST /api/v1/auth/logout                                             → 204
GET  /api/v1/auth/session                                            → 200 {authenticated, user|null}
GET  /api/v1/health                                                  → 200 {status,"revision":"0001"}

POST /api/v1/chat
  headers: X-SUNIL-Client: web · X-Request-Id: <uuid4> · Cookie
  body:    {message: string(1..8000), conversation_id: string|null}
  → 200 {request_id, conversation_id, outcome: "ok"|"failed",
         message: {id, role:"assistant", content, created_at} | null,
         task: {id, status, assigned_agent} | null,
         failure: {kind, known_projects?: [{key, display_name}]} | null,
         trace: [{stage, offset_ms, detail}],
         usage: {input_tokens, output_tokens, cost_usd}}
  → 401 no session · 403 missing X-SUNIL-Client / bad Origin · 422 bad body or bad X-Request-Id

GET  /api/v1/chat/{request_id}/events        (SSE, withCredentials)   [T12 — optional, flag-gated]
  event: stage  data: {stage, offset_ms, detail}
  event: done   data: {outcome}
  : ping                                     (heartbeat, 15 s)

GET  /api/v1/trace/{request_id}              → 200 {stages[], llm_calls[], tool_calls[]}   [T13 — optional]
```

`failure.kind` ∈ `provider_error | tool_failed | plan_rejected | unknown_project` → the Designer's
`ErrorCard` variants `generic | tool_failed | plan_rejected | unknown_project`.
**The §5.3 turn-deadline breach maps to `provider_error`** — no new kind, no new copy.

`stage` ∈ the twelve NFR-020 names: `message_received, context_loaded, memory_retrieved,
model_selected, llm_io, plan_created, agent_started, tool_requested, permission_decision, tool_result,
agent_result, final_response`. **Each appears at most once per turn**; retries are counted inside
`detail`, not as extra entries.

`usage` sums **all provider attempts** in the turn, including failed ones that consumed input tokens.

**The API sends enums and data. The web app owns every human-readable string** — labels, phase names
and all failure copy (`ARCHITECTURE_V1.md` §11.2).

---

## 7. Exit-test coverage map

| Exit test | Made passable by |
|---|---|
| **ET-1** coherent answer traceable to real data | T8 + T10 + T11b + T16 |
| **ET-2** Task + Workflow + schema-valid plan JSON | T2 + T9 + T11a + T11b |
| **ET-3** `assigned_agent` = Project Manager | T10 + T11b |
| **ET-4** exactly one ToolCall, decision `ALLOW` | T7 + T8 |
| **ET-5** tool result feeds the analysis call; prose, not JSON | T6 + T10 *(and ADR-015 makes the answer **be** that analysis)* |
| **ET-6** all twelve stages, in order, from logs alone | **T4** + T11a + T11b |
| **ET-7** malformed plan → zero ToolCalls | **T9** |
| **ET-8** transient failure recovers or fails cleanly | T6 + T11b |
| **ET-9** cost record per **provider attempt**, non-zero tokens | T2 + T6 |
| **ET-10** no secret in any prompt or persisted log | **T4** + T19 |
| **ET-11** unknown project answered, not crashed or faked | T3 + T9 + T11b + T16 |
| *(recommended)* **ET-12** external content is projected/sanitised before it reaches a model | T8 + T19 — **see §10, step 13. No current exit test covers it.** |

---

## 8. Schedule — recalculated on the corrected graph

### 8.1 Estimates

Hours are *engineer-agent working hours* including the task's own unit tests and `ruff`. They exclude
review, CI and merge latency, which §8.3 adds separately.

| Task | h | | Task | h | | Task | h |
|---|---|---|---|---|---|---|---|
| T1 foundation + trace iface | 2.0 | | T8 tools + GitHub | 4.0 | | T15 chat components | 4.0 |
| T2 data layer (12 tables + capture) | 4.0 | | T9 plan validation + guards | 3.5 | | T16 API client + useTurn | 4.0 |
| T3 registries (6 files) | 3.0 | | T10 agent framework + PM | 3.0 | | T18 QA exit harness | 5.0 |
| T4 trace spine | 3.0 | | T11a gateway + envelope | 3.0 | | T19 security tests | 3.0 |
| T5 API skeleton | 3.0 | | T11b orchestrator turn | 3.5 | | T20 integration | 3.0 |
| T6 router + provider | 4.0 | | T14 web scaffold | 2.0 | | T21 CI | 1.5 |
| T7 permissions | 1.0 | | | | | *optional:* T12 2.5 · T13 1.0 · T17 2.5 | |

**MUST-HAVE total: 59.5 h** across seven lanes. Including the three optional tasks: 65.5 h.
Total volume is not the constraint — **the critical path is.**

### 8.2 The resource-constrained schedule

Hour offsets from build start (H+0). Three backend lanes; each lane is one worker, so tasks within a
lane are serial.

| H+ | BE-1 | BE-2 | BE-3 | FE | QA / SEC / OPS |
|---|---|---|---|---|---|
| 0–2 | **T1** | — | — | **T14** | T18 red suite · **T21 CI** |
| 2–5 | **T2** | **T3** | — | **T15** | T18 · T19 boundary tests |
| 5–6 | T2 | **T6** | **T7** | T15 | T18 · T19 |
| 6–9 | **T4** | T6 | *(idle / assist QA)* | **T16** | T18 |
| 9–12 | **T5** | **T8** | **T9** | T16 | T18 · T19 |
| 12–13 | **T11a** | T8 | T9 → done 12.5 | done | T19 |
| 13–15 | T11a | **T10** | *(T13 if reached)* | | T19 |
| 15–16 | *(wait on T10)* | T10 | | | |
| 16–19.5 | **T11b** | *(T12 if reached)* | | | |
| 19.5–22.5 | **T20** (with QA) | | | | **T19 injection tests** |

**Critical path: T1 → T2 → T4 → T8 → T10 → T11b → T20 = 22.5 h of build work.**

### 8.3 What that becomes in reality

| Component | Hours |
|---|---|
| Critical-path build work (§8.2) | 22.5 |
| Review + CI + merge latency, 7 critical-path tasks × ~0.75 h | +5.0 |
| **Best case, nothing bounces** | **27.5** |
| One QA or Security bounce on T8/T9/T11b (rework + re-review) | +2 to +4 |
| **Expected case** | **~30–31** |
| Two bounces, or one estimate miss on T8/T11b | +6 to +9 |
| **Bad case** | **~36–38** |

Against the calendar: build starts on the evening of 2026-08-14 and **M1 is due end of
2026-08-18** — the owner granted one extra day on 2026-08-14, on the strength of this section's
verdict, in preference to descoping. That is roughly **4 h tonight + four working days**. At a
sustainable **8 productive lane-hours per day** — and Team 18's own history says a review pass can
stall on a session limit — that is **~36 available hours**. At an optimistic 10 h/day it is ~44.

### 8.4 The verdict, stated plainly

> **M1's MUST-HAVE set fits the revised 2026-08-18 date in the expected case with ~5 h of slack,
> and survives one bounce. It fails only in the bad case (~36–38 h), which is exactly the
> scenario the extra day was bought to absorb.**
>
> *(Original verdict, against the superseded 2026-08-17 date, retained because the decision rests
> on it: the MUST-HAVE set fitted that date only in the best case, with about half an hour of
> slack, and missed it in the expected case by roughly one working day.)*

I am not compressing the estimates to make the arithmetic close, because the brief told me not to and
because a plan that only works if every task is a first-pass success is not a plan.

**The uncomfortable finding: descoping T12, T13 and T17 does not save the date.** They remove 6 h of
*lane* work and **zero hours from the critical path** — none of the three is on it. They are still
worth deferring (they clear the tail, where BE-1 and OPS would otherwise be busy during integration),
but nobody should believe they buy time on the deadline. They do not.

**What actually shortens the critical path, in order of value per hour of effort:**

| # | Lever | Buys | Cost |
|---|---|---|---|
| 1 | **Start the lanes tonight, 2026-08-14**, not tomorrow morning | ~4 h | free — it only needs Gate 2 closed |
| 2 | **Three backend lanes, not two** (§0.1) — otherwise T6 and T8 queue behind each other in BE-2 | ~2 h | one more agent |
| 3 | **T1 owns the trace interface** (§1.2 note) so T6/T8 do not wait on T4's implementation | ~2 h | 20 minutes of T1 |
| 4 | **T11 split into T11a/T11b** — T11a runs while T10 is still being built | ~2.5 h | already applied |
| 5 | **A 30-minute review SLA on the seven critical-path tasks.** Every hour a green branch waits for review is an hour of the milestone | ~2–3 h | DM/QA/SEC availability |
| 6 | **Pre-agree the review bar** for T8/T9/T11b — blockers only, `should`/`nit` findings recorded and fixed post-M1 | ~2 h | discipline, and a follow-up task |

Levers 2, 3 and 4 are already built into §8.2's numbers. Levers 1, 5 and 6 are **decisions for the
Delivery Manager and the owner**, and together they are worth 6–9 hours — the difference between the
expected case and the date.

**If that is not enough, this is what I recommend giving, in this order — and only in this order:**

1. **T12, T13, T17** — already agreed (§9). Take them off the board now, not on Day 3.
2. **Split the milestone at the exit tests.** Declare M1 on **2026-08-18** as *ET-1 … ET-11 green
   plus the chat happy path in the browser*, and take the frontend's polish — all four `ErrorCard`
   variants wired to live failures, `SuggestionChips`, `JumpToBottomPill`, the reduced-motion pass —
   into a short **08-18** tail. Nine of the eleven exit tests are backend-provable; the two with a UI
   half (ET-1, ET-11) need the happy path and one error card, not the full component set.
3. **T20's measurement scope** — three timed runs instead of five (saves ~0.5 h and costs nothing,
   since neither number is a p95).
4. **Move the milestone to 2026-08-18.** One extra day converts "fits only if nothing goes wrong"
   into "fits with a normal amount going wrong". It is the cheapest single purchase available and it
   is the owner's call, not mine.

**Never descoped, in any circumstance:** T4 (the trace spine), T7 (permissions), T9 + its guards
(plan validation), T19's ET-10 and step-13 sanitisation tests, and T21 (CI). Those are what make the
M1 claims true, and ET-6, ET-7 and ET-10 are graded on them. Descoping any of them does not make M1
early; it makes M1 false.

---

## 9. Scope classification — decided now, not on the day

**MUST HAVE** (the owner's review §14, plus T21 and the T11 split):

```
T1  Foundation + trace interface      T9  Plan validation + runtime guards
T2  Database (12 tables + capture)    T10 Project Manager agent
T3  Registries (6 config files)       T11a Conversation gateway + envelope
T4  Trace / audit / redaction         T11b Orchestrator turn
T5  API / authentication              T14 Web foundation
T6  Model Router + provider           T15 Chat components
T7  Permission engine                 T16 API client + useTurn
T8  GitHub tool + projection          T18 QA exit tests
T21 CI (gates every merge)            T19 Critical security tests
                                      T20 Integration
```

**OPTIONAL / POST-M1 — pre-classified, so nobody has to make the call under pressure:**

| Task | Why it is safe to drop | What carries the load instead |
|---|---|---|
| **T12** SSE progress | Cosmetic by construction (ADR-009, amended) | T16's fallback stepper — now the primary path; `SUNIL_PROGRESS_EVENTS=false` |
| **T13** Trace read endpoint | The trace already ships inside the chat response (§6) | `TraceDisclosure` reads the response payload |
| **T17** Docker stack | SQLite removes Docker from M1's execution path (ADR-001/005/013) | Nothing needs it in M1. **Exception: pull `dev-check.ps1` forward into T1** — it is 30 minutes and it catches the `localhost`/`127.0.0.1` cookie trap before it costs an afternoon |

Everything else on the MUST-HAVE list is mandatory. If the date is at risk, apply §8.4's four
recommendations — do not improvise a cut from the MUST-HAVE list.

---

## 10. The M1 acceptance walkthrough — the owner's 24 steps

Adopted verbatim from the owner's review §16 as **the** definitive M1 acceptance walkthrough. T20
walks it end to end with one request: **"Check on EasyClean Workforce."**

| # | Step | Covered by exit test | Task |
|---|---|---|---|
| 1 | Authenticate the user | — *(gap: no ET; FR-007 + `test_chat_requires_session`)* | T5 |
| 2 | Create a request ID | — *(gap: no ET; FR-004; ET-6 depends on it)* | T5 |
| 3 | Persist the user message | — *(gap: no ET; FR-021)* | T11a |
| 4 | Load conversation context | ET-6 (stage 2 present) | T11a |
| 5 | Send the request through the Model Router | ET-9 | T6 |
| 6 | Receive a structured plan | ET-2 | T6 + T9 |
| 7 | Validate the plan | **ET-7** (negative), ET-2 (positive) | **T9** |
| 8 | Create a Task and Workflow | **ET-2** | T11a |
| 9 | Start the Project Manager Agent | **ET-3** | T10 + T11b |
| 10 | Check agent tool permission | **ET-4** | T7 + T8 |
| 11 | Resolve the GitHub repository from configuration | ET-11 (negative only) + `test_repo_coordinates_never_come_from_plan` *(gap: no ET asserts the positive path)* | T3 + T8 |
| 12 | Execute a read-only GitHub operation | **ET-4** | T8 |
| 13 | **Project/sanitise external content before AI analysis** | **NO EXIT TEST — flagged. Covered by NFR-011/012 and three named security tests; ET-12 recommended** | **T8 + T19** |
| 14 | Analyse the result | **ET-5** | T10 |
| 15 | Return a coherent user-facing summary | **ET-1** | T10 + T11b |
| 16 | Store task state | ET-2/ET-3 partially *(gap: FR-065's ordered status history has no ET)* | T11a |
| 17 | Record cost | **ET-9** | T2 + T6 |
| 18 | Record model/provider calls | **ET-9** | T6 |
| 19 | Record permission decisions | **ET-4** | T7 + T8 |
| 20 | Record tool calls | **ET-4** | T8 |
| 21 | Emit all required trace stages | **ET-6** | T4 + T11a/b |
| 22 | Store no raw credentials/secrets | **ET-10** | T4 + T19 |
| 23 | Fail safely on malformed plans | **ET-7** | T9 + T11b |
| 24 | Fail safely on provider/tool errors | **ET-8** | T6 + T8 + T11b |

### 10.1 Gaps, flagged rather than papered over

Five of the twenty-four steps are not asserted by any of ET-1…ET-11. Four are minor; one is not.

- **Step 13 — prompt-injection defence on external content — is the one that matters, and the owner
  is right to call it out.** It is a *real M1 control, not a deferred one*: GitHub content reaches an
  LLM in every single successful turn. It is implemented in `tools/github/projection.py` (allow-list,
  length caps, **issue and PR bodies excluded entirely**) and in T10's `<untrusted_tool_result>`
  wrapping with delimiter escaping, and it is tested by three named tests in T19
  (`test_tool_result_projection_excludes_issue_bodies`,
  `test_projection_escapes_the_untrusted_delimiter`,
  `test_no_unprojected_github_payload_reaches_a_prompt`) plus the T-15 injection test.
  **Recommendation to the Delivery Manager: add ET-12 to the SRS** — *"Given a repository whose
  recent activity contains an embedded instruction, When the owner requests a status check, Then no
  unprojected external payload appears in any `llm_calls.request_messages` row, issue/PR bodies are
  absent, and the agent's behaviour is unchanged."* Until that exists, the three tests are mandatory
  and non-descopable, and §7's table lists ET-12 as recommended.
- **Steps 1, 2, 3 and 16** are covered by requirements (FR-007, FR-004, FR-021, FR-065) and by unit
  and integration tests, but by no *exit* test. They are all prerequisites of ET-1/ET-2/ET-6 in
  practice — a turn that failed any of them could not produce a passing ET-6 — so I do not recommend
  new exit tests for them. Recorded here so the coverage claim stays honest.

---

## 11. Known traps, collected

Each of these has cost someone a day somewhere. They are here so they cost nobody a day here.

1. `python3` launches the Microsoft Store stub on this machine. Always `python`.
2. Mixing `127.0.0.1` and `localhost` between the two dev servers silently withholds the session
   cookie — different **sites**, so `SameSite=Lax` blocks it on POST. Both must be `localhost`.
3. `allow_origins=["*"]` with `allow_credentials=True` is rejected by every browser. Use `WEB_ORIGIN`.
4. Starlette applies the **most recently added** middleware outermost. Use the explicit constructor
   list and put CORS first, or your 401 arrives without CORS headers and looks like a network error.
5. `create-next-app` now scaffolds Tailwind v4. Scaffold without it and add `3.4.19` explicitly.
6. GitHub's `/issues` endpoint also returns pull requests. Filter on the `pull_request` key.
7. `output_config` JSON Schema does **not** support `minimum`/`maximum`/`minLength` or nullable union
   types. Use `enum` sentinels and validate ranges in Pydantic.
8. `Numeric` on SQLite is lossy and warns. Money is `BigInteger` micro-USD.
9. The `TraceBus` is in-process — `uvicorn --workers 1` or progress events break silently.
10. `pip index versions` cannot parse extras; check `psycopg`, then install `psycopg[binary]`.
11. **`pytest` exits 5 when it collects no tests.** A CI job that treats only exit 1 as failure is
    green on an empty suite. T21 treats 5 as failure.
12. **Never assert "exactly three LLM calls"** — or exactly any number. One transient 429 makes it
    four. Count `llm_calls` rows by `purpose`, or assert `>= 2` (A-2, ADR-015).
13. **Do not commit to `main`.** If `git status` in your worktree says `On branch main`, stop and
    tell the Delivery Manager (`GIT_WORKFLOW.md` rule 1).
