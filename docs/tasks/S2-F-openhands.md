# S2-F — the OpenHands developer-agent seam

**Stream F · branch `task/S2-F-openhands` (from `V2` @ 6280f48) · backend_engineer · 2026-09-12**

Scope delivered: the **governed seam**, not a live OpenHands run. ADR-030 §4's policy
(`push_branch: allow`, `merge_main: ask_user`, through C4) is implemented and proved at agent
level against the real plan validator, the real Tool Manager and C4 §6's approvals fake. The
engine itself is one config decision away — and that decision is an ADR, not an edit (see
§4).

---

## 1. The seam

```
sunil/agents/developer/
  client.py          OUR seam: OpenHandsClient protocol + TaskSpec/RunResult/GitIntent/EngineError
  openhands_http.py  the ONE module that knows OpenHands' HTTP shape
  agent.py           DeveloperAgent — the governed agent
```

```python
class OpenHandsClient(Protocol):
    async def submit(self, spec: TaskSpec) -> str        # -> run_id
    async def status(self, run_id: str) -> RunState      # queued | running | succeeded | failed
    async def result(self, run_id: str) -> RunResult
```

Three calls, and **no vendor vocabulary anywhere in it**: no URL, no header, no field name, no
lifecycle string. Every OpenHands-specific string in the system is in one constants block at the
top of `openhands_http.py`, and the tests pin each one. That containment is the verifiable part of
ADR-030's "replaceable vendor behind a SUNIL-owned seam".

**What is deferred to the first live boot.** The *contents* of that constants block — paths
(`/api/conversations`), request keys (`initial_user_msg`, `repository`, `selected_branch`),
response keys (`conversation_id`, `status`, `last_error`, `final_message`) and the lifecycle
strings in `STATE_MAP`. They were written **without access to a running instance** (multi-GB image,
needs an LLM key this environment does not hold) and are therefore **unverified**. The module says
so in code — `VENDOR_MAPPING_STATUS == "unverified-until-first-live-boot"` — and a test asserts
it, so "is this live-ready?" has a machine-readable answer rather than a comment to trust.
Correcting it at first boot is an edit to that block plus the test that pins it, and **no change
to any governed behaviour**.

Two mapping choices should survive that correction:

* an **unmapped lifecycle string raises** instead of defaulting. A default of "finished" would make
  the agent fetch a report for a run still writing to the branch.
* the **run report is our contract, not the vendor's**. OpenHands has no native "which git writes
  do you want" output, so the agent's prompt carries `client.REPORT_CONTRACT` (a fenced JSON block)
  and the adapter parses it. A report that never arrives, or does not parse, is a **failed run** —
  which means zero git operations. The parse is the only thing between an autonomous loop and our
  remote, so it fails closed.

## 2. What is governed, and where

`ARCHITECTURE_V2.md` §3 states Stream F as "consumes C1 (**its git ops are tool calls**) + C4". That
sentence is the design:

| Thing | Governed how |
|---|---|
| The delegation to the sandbox | **Not** a tool call. A sandboxed run that touches nothing outside its own container is not an action on the world; the chokepoint governs actions on the world. |
| `push_branch` | C1 tool call `github_mcp.push_branch` → permission matrix → `allow` → executes, audited. |
| `merge_main` | C1 tool call `github_mcp.merge_main` → permission matrix → `ask_user` → **parked via C4**, turn ends. |

**The work order is a NON-tool plan step** — `action: "fix_and_pr"`, `tool: "none"` — addressed to
agent `developer`. Deliberately not a `developer.fix_and_pr` tool triple: that would need an entry
in `config/tools.yaml` with no adapter behind it, i.e. a tool the plan validator must reject
(`unknown tool`) and the chokepoint could never execute. The step shape as written is accepted by
the **real** validator today (`tests/unit/agents/harness.py` mints every test plan through
`validate_plan`) — layer 4 does not constrain `action` on a non-tool step.

`github_mcp`, not the native `github` tool, because `config/tools.yaml` declares the native one
"GitHub (native, read-only)" and the dashboard's own worked example already renders the approval
card as `github_mcp.merge_main` (`docs/design/mockups/01-approvals-queue.html`).

### The engine's reply is untrusted input (C1 §3)

It is the output of an autonomous loop whose context held repository files and issue bodies. Four
controls, each with a test:

1. **It cannot choose the verb.** `GitIntent.operation` is matched against the closed
   `GOVERNED_OPERATIONS = ("push_branch", "merge_main")` *before* the chokepoint. Anything else
   fails the turn closed. (A permission `deny` would be the right outcome for the wrong reason: it
   would say "this agent may not deploy" when what we mean is "this engine does not pick verbs".)
2. **It cannot choose the branch freely.** `validate_branch` enforces charset/shape, no `..`, the
   work order's prefix, not the base branch, and not a protected branch. Without the last check a
   `push_branch: allow` grant becomes an ungoverned write to the branch `merge_main: ask_user`
   exists to protect.
3. **It cannot choose the params.** The agent builds `{project_key, branch, base_branch}` itself
   from values it validated. Nothing is copied from the reply.
4. **Its prose never becomes SUNIL's voice.** `AgentResult.content` is SUNIL-composed. `content`
   lands in the conversation, and the conversation is the next turn's prompt; the engine's own
   words go to `tool_details` as evidence instead. (This agent also makes **no LLM call** at all —
   ADR-015's analysis call exists to narrate tool output, and feeding untrusted prose to a model to
   be re-emitted as SUNIL's voice would re-open this through the back door.)

Also: `TaskSpec` carries a `project_key`, never a repository — the repository is resolved by the
client from the project registry, exactly as the native GitHub tool resolves `owner/repo`
(`config/tools.yaml`: "owner/repo come from config/projects.yaml via the wiring code, NEVER from
the plan"). No plan can point the engine at an arbitrary repository. And the agent **holds no git
credential**: there is no code path that could carry one (§4).

## 3. Parked-merge evidence

`tests/unit/agents/test_developer_agent.py::test_merge_intent_parks_an_approval_and_ends_the_turn`
runs a two-intent report through the **real** `ToolManager` with `FakeApprovalsService` behind it
and asserts, on the C4 row itself:

* `result.kind == "parked"`, with `approval_id` / `expires_at` from the manager's typed
  `ApprovalRef` (not mined out of `data` — C1 v1.2.0 ruling R8);
* `approvals[id].status is PENDING`, `(tool, operation) == ("github_mcp", "merge_main")`,
  `agent_id == "developer"`, and a SUNIL-composed summary naming the operation;
* the parked `continuation` is resumable **and specific**: alongside ADR-031's plan/cursor/ids it
  carries `engine`, `run_id`, `intent_index` and `branch`, so a resume lands on that merge and no
  other rather than re-delegating the step;
* `push_branch` executed and `merge_main` did **not**.

A companion test proves the absence of a grant is a `permission_denied`, not a park — default-deny
stays the engine's structure, not this agent's.

## 4. Compose / docker.sock decision

**The service block is committed COMMENTED OUT** in `infra/docker-compose.yml`, with
`profiles: [dev-agents]`, the ADR-032 port pair (`127.0.0.1:3400 -> 3000`) and the full rationale
in place. That is the outcome of the runtime decision, not an unfinished edit.

OpenHands' default runtime spawns a sandbox container per conversation by talking to the host
Docker daemon through a bind-mounted `/var/run/docker.sock`. The wave-1 security review forbade
that mount, and the threat-model implication is specific: the socket is not a permission but a
privilege escalation (anything reaching it can start a `privileged: true` container with the host
root filesystem mounted), so the new SUNIL→engine boundary would become *agent-authored code →
host root* — reaching the postgres volume (`audit_events`, `approvals`), n8n's credential vault
and `infra/.env.litellm`, i.e. collapsing the existing boundaries rather than adding one. And the
code in that sandbox is written by a loop whose context includes issue bodies: exactly C1 §3's
untrusted input.

Alternatives investigated:

| Option | Verdict |
|---|---|
| **Remote runtime** (`SANDBOX_REMOTE_RUNTIME_API_URL`) | The option that fits the rule — no socket in this container. Needs a runtime API endpoint we do not host. Pointing it at a third-party hosted runtime ships client repository contents off-machine: a privacy-class decision (ADR-030's OmniRoute reasoning verbatim), not this stream's to take. |
| **Local runtime** | No socket, but removes the isolation between the agent and the service governing it. Rejected. |
| **Kubernetes / E2B / Modal** | Each a new hosted dependency. |

So enabling the service has a prerequisite that is an **ADR, not an edit**. The SUNIL-side seam is
complete and tested without it.

**The sandbox's credential, documented not implemented** (as briefed): the scoped git token is
delivered to the *engine* at *its* boot, in its own `infra/.env.openhands` (never the shared root
`.env` — the LiteLLM finding). Fine-grained, one repository, `contents:read/write` only, no admin,
no org scope. It is the only git authority the engine has, `merge_main` remains SUNIL's own
approval-gated tool call, and branch protection on `main` is the server-side backstop.

**CI note (verified, not assumed):** `docker compose config` **omits** profiled services — confirmed
with Compose v5.5.1 on 2026-09-12 against a two-service probe. So the port/loopback parity gate in
`.github/workflows/ci.yml` will not see `openhands` even once it is uncommented. The gate's
`EXPECTED` map was therefore **left unchanged** — adding `openhands` to it now would fail the build,
because the service is absent from the default resolved config. All four compose gates were re-run
locally after the edit and pass (§6).

## 5. Handover requests (other owners' files — not touched)

1. **`config/permissions.yaml`** (Stream E's file) — the execution decision. `config/agents.yaml`
   carries only the planning grant:

   ```yaml
   agents:
     developer:
       github_mcp:
         push_branch: allow      # ADR-030 §4
         merge_main: ask_user    # ADR-030 §4 — parks via C4
   ```

   Nothing else. In particular **no** `n8n_mcp` and **no** `github.list_recent_activity` for this
   agent until a task needs them.

2. **`config/tools.yaml`** (Stream A/E) — `github_mcp` must expose the two operations, both
   `read_only: false`, with params models accepting exactly
   `{project_key, branch, base_branch}` (`extra="forbid"`). Until they exist, a plan step naming
   them is rejected at layer 4 — the correct fail-closed state for a half-wired tool. The shape the
   agent calls with is pinned by `tests/unit/agents/harness.py::StubGitAdapter`.

3. **`settings.py` / ADR-033** — `SUNIL_OPENHANDS_BASE_URL`, and `"openhands"` added to the frozen
   named-host set. ADR-033 already anticipates this by name: "`openhands` joins it in Phase V2-D".

4. **`.github/workflows/ci.yml`** (DevOps) — a second port-gate pass with
   `--profile dev-agents`, added *before* the compose block is uncommented (§4).

5. **`core/agent_framework/base.py` + `orchestrator/turn.py`** (spine owner) — `AgentResult.kind`
   is a closed literal and `turn.py` maps only `tool_failed` / `provider_error` onto a C5 failure,
   so a new member would be silently treated as **success**. An engine failure is therefore reported
   today as `kind="tool_failed"` with the honest C1 §4 kind in `tool_error_kind`
   (`upstream_error` / `transport_error` / `timeout` / `invalid_params`) and the engine's own
   `failure_kind` string preserved unmapped in `tool_details`. If a distinct `engine_failed` kind is
   wanted, it needs both files changed together.

6. **`plan_schema.py`** (orchestrator owner) — `"fix_and_pr"` should join `NON_TOOL_ACTIONS` so a
   constrained-decode planner can *emit* the work-order step. Layer 4 already accepts it; layer 1 is
   the provider's grammar, so without this the step can only be built by SUNIL code, not planned.
   One line, no behaviour change.

## 6. Verification

| Gate | Result |
|---|---|
| Full suite (SQLite leg), run 1 | **993 passed, 4 skipped** (baseline 955 + 38 new) |
| Full suite, run 2 | **993 passed, 4 skipped** |
| `yamllint -c .yamllint.yml infra/ .github/workflows/` | clean (exit 0) |
| compose resolves against `.env.example` | OK, no unresolved variables |
| compose refuses with NO env file | OK (fail-closed secret guard intact) |
| port/loopback/ADR-032 parity gate | OK — `postgres:5433, litellm:4000, n8n:5680`, 3 ports, all `127.0.0.1` |
| Mutation check: delete the `GOVERNED_OPERATIONS` guard | test goes red |
| Mutation check: delete the `PROTECTED_BRANCHES` guard | test goes red (after the parametrisation was corrected — see below) |

The second mutation check first passed with the guard deleted, because the bare names `main` /
`master` / `develop` are also caught by the prefix and base-branch rules. The parametrisation now
includes `sunil/main`, which only `PROTECTED_BRANCHES` catches, so the test tests what its name
says.

Not verified, and not claimable: anything against a live OpenHands instance (§1).

## 7. Files

| File | Change |
|---|---|
| `apps/api/sunil/agents/developer/{__init__,client,openhands_http,agent}.py` | new |
| `apps/api/tests/unit/agents/{__init__,harness}.py` | new |
| `apps/api/tests/unit/agents/test_developer_agent.py` | new (20 tests) |
| `apps/api/tests/unit/agents/test_openhands_http.py` | new (16 tests) |
| `apps/api/tests/unit/agents/test_developer_registration.py` | new (2 tests) |
| `config/agents.yaml` | additive — the `developer` agent |
| `infra/docker-compose.yml` | additive — the commented `openhands` block |
| `docs/tasks/S2-F-openhands.md` | this file |
