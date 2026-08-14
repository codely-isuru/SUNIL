# SUNIL V1 / M1 — Architecture & Build Plan Review Recommendations

**Review Basis**
- `ARCHITECTURE_V1.md`
- `M1_BUILD_PLAN.md`
- Original SUNIL V1 → V3 roadmap

**Review Date:** 2026-08-14  
**Recommendation:** **Approve the architecture direction after targeted corrections. Revise the M1 build plan before execution.**

---

# 1. Executive Summary

The current SUNIL V1 architecture is strongly aligned with the original project vision:

- SUNIL remains the product and orchestration layer.
- Claude, OpenAI, Codex, local Qwen, and future models remain interchangeable intelligence providers.
- The Central Orchestrator remains deterministic software rather than an LLM.
- LLMs are used for natural-language interpretation, reasoning, analysis, and response generation.
- Agents are roles/workflows, not permanently attached to a specific model.
- Tool execution is permission-controlled and auditable.
- V1 is cloud-first.
- V2 introduces local AI.
- V3 introduces personalised/local-first intelligence.
- The project begins with a narrow vertical slice rather than attempting the full Agentic OS at once.

The architecture is stronger and more implementation-ready than the original conceptual roadmap.

However, several build-plan and wording issues should be corrected before Gate 2 is closed.

---

# 2. Overall Verdict

## Architecture

**Score: 9/10**

**Recommendation:** Approve after the corrections in this document.

The following architectural variations from the original roadmap should be accepted:

1. Use one installable `sunil` Python package instead of multiple top-level import roots.
2. Rename ambiguous framework packages:
   - `core/models` → `core/routing`
   - `core/agents` → `core/agent_framework`
   - `core/tools` → `core/tool_framework`
3. Use SQLite for M1 development while keeping PostgreSQL as the V1 target.
4. Defer Redis until an actual distributed/scheduler use case exists.
5. Defer pgvector until RAG/vector retrieval is implemented.
6. Use SSE for M1 progress instead of WebSockets.
7. Keep agent configuration in YAML rather than duplicating it in an `agents` database table.
8. Version the API under `/api/v1`.

These are implementation improvements, not deviations from the SUNIL product direction.

---

# 3. Build Plan

## Build Plan Score

**Score: 7.5/10**

The individual tasks are well-defined and the exit-test approach is strong.

The main problem is that the stated dependency graph and critical path underestimate the real sequencing required to reach T11 and T20.

This should be corrected before development begins.

---

# 4. BLOCKER — Correct the Critical Path

The current build plan presents this as the critical path:

```text
T1 → T2 → T4 → T5 → T11 → T20
```

This is incomplete.

T11 depends on:

```text
T2
T4
T5
T9
T10
```

T10 depends on:

```text
T3
T6
T8
T9
```

T9 depends on:

```text
T3
T6
```

T8 depends on:

```text
T2
T3
T4
T7
```

Therefore the real build has several critical branches.

### Branch A

```text
T1
 ↓
T3
 ↓
T6
 ↓
T9
 ↓
T10
 ↓
T11
 ↓
T20
```

### Branch B

```text
T1
 ↓
T2
 ↓
T4
 ↓
T8
 ↓
T10
 ↓
T11
 ↓
T20
```

### Branch C

```text
T1
 ↓
T2
 ↓
T4
 ↓
T5
 ↓
T11
 ↓
T20
```

## Recommendation

Recalculate the schedule using these dependencies.

Do not describe T6, T8, T9, or T10 as slack work.

T9 must finish before T10 can complete, and T10 must finish before T11 can execute the full vertical slice.

---

# 5. BLOCKER — Do Not Allow Multiple Agents to Commit Directly to `main`

The build plan currently allows several agents to commit to `main` concurrently while relying on strict file ownership.

File ownership does not fully protect Git repository state.

## Recommended model

Each implementation task should use a separate branch or Git worktree.

```text
main
 │
 ├── task/T1-foundation
 ├── task/T3-registries
 ├── task/T6-router
 ├── task/T14-web
 ├── task/T18-qa
 └── task/T19-security
```

Prefer separate worktrees for parallel autonomous workers:

```text
/worktrees/
  be-core/
  be-integrations/
  frontend/
  qa/
  security/
```

Integration process:

```text
Engineer / Agent
      ↓
Task Branch
      ↓
Tests
      ↓
Review / QA
      ↓
Controlled Merge
      ↓
main
```

## Rule

**No autonomous implementation agent should directly commit to shared `main` while other agents are running concurrently.**

---

# 6. BLOCKER — Clarify "Three LLM Calls"

The architecture says that M1 has exactly three LLM calls:

1. Plan
2. Analysis
3. Final response

That is correct only at the **logical-stage level**.

It is not necessarily three provider API calls.

## Why

Provider retries may result in:

```text
Logical Plan Request
  ├── provider attempt 1
  ├── provider attempt 2
  └── provider attempt 3
```

Plan validation may also trigger multiple logical planning attempts.

Therefore one turn can produce substantially more than three provider requests.

## Recommended wording

Replace:

> There are exactly three LLM calls in an M1 turn.

With:

> An M1 turn contains three logical LLM purposes: planning, analysis, and final-response synthesis. Each logical request may result in multiple provider attempts due to retries or validation recovery.

This distinction matters for:

- Cost tracking
- Latency
- Rate limits
- Trace interpretation
- p95 performance targets

---

# 7. BLOCKER — Strengthen `ValidatedPlan` Runtime Enforcement

The `ValidatedPlan` architecture is very good.

The current wording describing it as "unforgeable" or claiming that there is "no expressible code path" from raw output to execution is too strong for Python.

Python type annotations and module-private variables are not security boundaries.

## Keep the current design

```text
Raw LLM Output
      ↓
Structured output validation
      ↓
Pydantic validation
      ↓
Registry validation
      ↓
ValidatedPlan
```

## Add explicit runtime checks

Example concept:

```python
if not isinstance(plan, ValidatedPlan):
    raise InvalidPlanExecution(...)
```

The tool execution path should also require trusted execution metadata such as:

```text
validated_plan_id
request_id
task_id
agent_id
```

For stronger future enforcement, the Tool Manager can verify that the referenced stored plan has:

```text
validated = true
```

before privileged execution.

## Recommended final chain

```text
LLM output
   ↓
Schema validation
   ↓
Pydantic validation
   ↓
Registry validation
   ↓
ValidatedPlan
   ↓
Runtime execution guard
   ↓
Agent permission check
   ↓
Tool parameter validation
   ↓
Permission engine
   ↓
Tool adapter
```

The design remains strong; only the security claim should be made more precise.

---

# 8. HIGH PRIORITY — Add Minimal CI Earlier

The current plan defers CI significantly.

For SUNIL, several autonomous agents and QA/security lanes will work in parallel.

Minimal CI should be introduced early.

## Minimum CI

### Backend

```text
ruff
pytest
```

### Frontend

```text
typecheck
build
```

### Security

```text
import-boundary tests
critical security tests
```

## Recommended flow

```text
Task Branch
   ↓
CI
   ↓
Review
   ↓
Merge
```

Deployment CI can remain deferred.

Basic validation CI should not.

---

# 9. HIGH PRIORITY — Resolve the 2026-08-17 Date Conflict

The documents currently disagree on whether **2026-08-17** means:

- Build start, or
- M1 due date.

This must be resolved before execution.

Once decided, update all related documents consistently:

```text
ROADMAP.md
REQUIREMENTS_V1.md
STATUS.md
ADR-000
M1_CHAT_SPEC.md
M1_BUILD_PLAN.md
```

Do not allow different team agents to operate with different milestone assumptions.

---

# 10. HIGH PRIORITY — Add Training Data Capture Policy

The architecture correctly captures:

- User messages
- Plans
- LLM inputs
- LLM outputs
- Tool calls
- Tool results
- User corrections
- Task results

This is valuable for V3 personalisation.

However, secret redaction alone is not enough.

Sensitive business/customer content may not contain API keys but still should not automatically become training data.

## Add capture policy

Recommended values:

```text
NONE
METADATA_ONLY
REDACTED_FULL
FULL_LOCAL_ONLY
```

Add or plan these metadata fields:

```text
sensitivity
retention_class
training_eligible
capture_policy
```

Example:

```text
GitHub commit title
→ training_eligible = true

Password / API token
→ never stored

Payment/card data
→ never stored

Private personal information
→ FULL_LOCAL_ONLY

Client support conversation
→ configurable sensitivity
```

This should be designed in V1 even if full training does not begin until V3.

---

# 11. MEDIUM PRIORITY — Consider Removing the Third M1 LLM Call

Current flow:

```text
Planning LLM
     ↓
GitHub Tool
     ↓
Analysis LLM
     ↓
Final Response LLM
     ↓
User
```

For the final multi-agent SUNIL architecture, the final synthesis step is useful.

For M1, however, there is:

- One Project Manager Agent
- One GitHub tool
- One analysis result

The Project Manager analysis already generates a short user-facing summary.

## Recommended M1 simplification

```text
Planning LLM
     ↓
GitHub
     ↓
PM Analysis LLM
     ↓
AgentResult.summary
     ↓
final_response trace stage
     ↓
User
```

The system should still emit the `final_response` trace stage.

It simply does not require a third model request.

### Benefits

- Lower latency
- Lower cost
- Lower failure surface
- Easier M1 debugging

Introduce a dedicated final-response synthesiser later when SUNIL has multiple simultaneous agent results.

---

# 12. MEDIUM PRIORITY — Clarify Config Deployment Behaviour

The architecture correctly keeps agent configuration in YAML.

However:

> "changing configuration requires no code deployment"

is only fully true if deployment infrastructure treats the config as external/mounted configuration.

If YAML files are baked into a Docker image, updating them still requires a deployment.

## Recommendation

Keep the YAML architecture but define the V1 deployment policy:

```text
config/
  agents.yaml
  permissions.yaml
  models.yaml
  projects.yaml
  tools.yaml
```

should be mounted or otherwise separately deployable where practical.

For local development, restart-on-config-change is sufficient.

---

# 13. MINOR — Correct the Table Count

The build plan says T2 creates "all eleven tables" but lists twelve:

1. users
2. conversations
3. messages
4. workflows
5. tasks
6. task_status_events
7. plans
8. tool_calls
9. approvals
10. memories
11. llm_calls
12. audit_events

Change **eleven** to **twelve**.

---

# 14. Recommended M1 Scope

For the three-day M1, prioritise only what proves SUNIL's architecture.

## MUST HAVE

```text
T1  Foundation
T2  Database
T3  Registries
T4  Trace / Redaction
T5  API / Authentication
T6  Model Router
T7  Permission Engine
T8  GitHub Tool
T9  Plan Validation
T10 Project Manager Agent
T11 Orchestrator
T14 Web Foundation
T15 Chat Components
T16 API Client
T18 QA Exit Tests
T19 Critical Security Tests
T20 Integration
```

## OPTIONAL / POST-M1 IF TIME IS LIMITED

```text
T12 SSE progress
T13 Dedicated trace-read endpoint
T17 Docker stack
```

Reasons:

### T12

The frontend already has a fallback progress stepper.

### T13

The chat response already contains the trace.

### T17

SQLite removes Docker/PostgreSQL from the M1 execution path.

The infrastructure files can follow immediately after the vertical slice is working.

---

# 15. Recommended M1 Runtime Architecture

```text
                      USER
                       │
                       ↓
                    CHAT UI
                       │
                       ↓
             Conversation Gateway
                       │
                       ↓
              Central Orchestrator
                       │
                       ↓
                  Model Router
                       │
                       ↓
                     Claude
                  PLAN REQUEST
                       │
                       ↓
                 ValidatedPlan
                       │
                       ↓
             Project Manager Agent
                       │
                       ↓
               Permission Engine
                       │
                       ↓
                  GitHub Tool
                       │
                       ↓
                     Claude
                    ANALYSIS
                       │
                       ↓
                 AgentResult
                       │
                       ↓
             final_response stage
                       │
                       ↓
                     USER
```

Supporting every stage:

```text
Trace
Audit
Redaction
Permissions
Structured Plans
Cost Tracking
QA Tests
Security Tests
```

---

# 16. Recommended M1 Success Test

M1 is complete when this request works end-to-end:

> Check on EasyClean Workforce.

SUNIL should:

1. Authenticate the user.
2. Create a request ID.
3. Persist the user message.
4. Load conversation context.
5. Send the request through the Model Router.
6. Receive a structured plan.
7. Validate the plan.
8. Create a Task and Workflow.
9. Start the Project Manager Agent.
10. Check agent tool permission.
11. Resolve the correct GitHub repository from configuration.
12. Execute a read-only GitHub operation.
13. Project/sanitise external content before AI analysis.
14. Analyse the result.
15. Return a coherent user-facing summary.
16. Store task state.
17. Record cost.
18. Record model/provider calls.
19. Record permission decisions.
20. Record tool calls.
21. Emit all required trace stages.
22. Store no raw credentials/secrets.
23. Fail safely on malformed plans.
24. Fail safely on provider/tool errors.

---

# 17. Recommended Immediate Actions Before Gate 2 Approval

- [ ] Fix the M1 critical-path/dependency graph.
- [ ] Replace concurrent direct-to-main commits with branches/worktrees.
- [ ] Resolve the August 17 date ambiguity.
- [ ] Change "three LLM calls" to "three logical LLM stages".
- [ ] Strengthen runtime enforcement around `ValidatedPlan`.
- [ ] Add minimal CI to the near-term plan.
- [ ] Add training/capture privacy metadata.
- [ ] Correct the 11/12 table typo.
- [ ] Decide whether to remove the third LLM call from M1.
- [ ] Pre-classify T12/T13/T17 as optional if schedule pressure exists.
- [ ] Close Gate 2.
- [ ] Begin the vertical slice.

---

# 18. V1 → V3 Alignment Check

The reviewed architecture does **not** change SUNIL's long-term roadmap.

```text
==================================================
V1 — CLOUD-FIRST SUNIL
==================================================

Dashboard / Chat / Voice
Central Orchestrator
Model Router
Claude / OpenAI / Codex
Agents
Tools
Permissions
Memory
Human approval

Result:
Functional Agentic OS


                    ↓


==================================================
V2 — HYBRID SUNIL
==================================================

Add local Qwen
Privacy-aware routing
Local voice
Agent collaboration
Autonomous workflows
Shadow evaluation
Cloud escalation

Result:
Private hybrid Agentic OS


                    ↓


==================================================
V3 — PERSONALISED SUNIL
==================================================

Personal training dataset
Fine-tuned local model
Local-first intelligence
Proactive operation
Autonomous delegation
Controlled computer access
Continuous learning

Result:
Personal autonomous AI operating system
```

---

# 19. Final Recommendation

**Approve the V1 architecture after the targeted corrections above.**

Do **not** redesign the architecture.

The fundamental decisions are sound:

> SUNIL is the permanent system.  
> Models provide intelligence.  
> Deterministic software controls privilege.  
> Agents represent roles/workflows.  
> Tools are permission-controlled.  
> Memory remains separate from model weights.  
> Local intelligence is added after V1 is stable.

The main work required before build execution is correcting the M1 dependency/scheduling model and strengthening a few operational/security details.

Once those corrections are made, M1 is ready to proceed.
