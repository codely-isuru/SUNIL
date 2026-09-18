# S3 — the `github_mcp` re-landing parcel (w2r3, ruling R16)

Lane: backend/integration. Branch `task/S3-github`, cut from `V2`.
Parcel discipline: **atomic** (R15) — the capture, the `server_tool:` bindings, the composed
`merge_main`, the config rows and the tests land together or not at all.

R16 (`docs/tasks/integration-w1-rulings.md`) names every step; this file is the round's task file
and therefore the home of **step 0's verbatim capture**.

---

## 0. The capture gate — VERDICT: **candidate CONFIRMED, one expected binding CORRECTED**

R16 part 2 made the successor a *gate*, not a hope: nothing lands against
`github/github-mcp-server` until the candidate is booted, its `tools/list` captured verbatim, and
that capture pinned in a test. Done, 2026-09-16.

### What was booted

| | |
|---|---|
| artefact | `ghcr.io/github/github-mcp-server` |
| digest | `sha256:508a0857ec762b1ab1cece29193345b501fab1dd9d1228a7b617062954cecac6` |
| `serverInfo` | `{"name": "github-mcp-server", "title": "GitHub MCP Server", "version": "v1.12.2"}` |
| transport | Docker stdio — `docker run -i --rm -e GITHUB_PERSONAL_ACCESS_TOKEN <digest> stdio` |
| protocol | client pinned `2025-06-18`; server answered `2025-06-18` (so `_check_protocol_revision` passes) |
| toolsets | server default (no `GITHUB_TOOLSETS` set); `readOnly=false`, `lockdownEnabled=false` |
| credential | the owner's `GITHUB_TOKEN`, read from `.env` into the CHILD environment only, under the name the server reads (`GITHUB_PERSONAL_ACCESS_TOKEN`). Never printed, never written to any artefact — the capture script aborts if the value appears in its own output |

The verbatim `initialize` + `tools/list` responses are recorded byte-for-byte at
`apps/api/tests/unit/github_mcp/fixtures/github_mcp_server_v1_12_2.json` and replayed through the
REAL adapter by `apps/api/tests/unit/github_mcp/test_recorded_handshake.py` (the Stream E
`n8n_2_38_5_mcp.json` pattern: a recording proves the shape CI will actually meet, a hand-written
double only proves the double agrees with itself).

### `tools/list`, verbatim — 45 tools

```
  add_comment_to_pending_review, add_issue_comment, add_reply_to_pull_request_comment, assign_copilot_to_issue,
  create_branch, create_or_update_file, create_pull_request, create_repository,
  delete_file, fork_repository, get_commit, get_file_contents,
  get_label, get_latest_release, get_me, get_release_by_tag,
  get_tag, get_team_members, get_teams, issue_read,
  issue_write, list_branches, list_commits, list_issue_fields,
  list_issue_types, list_issues, list_pull_requests, list_releases,
  list_repository_collaborators, list_tags, merge_pull_request, pull_request_read,
  pull_request_review_write, push_files, request_copilot_review, search_code,
  search_commits, search_issues, search_pull_requests, search_repositories,
  search_users, sub_issue_write, update_issue_comment, update_pull_request,
  update_pull_request_branch
```

### R16's four expected bindings, confirmed or falsified

| SUNIL operation | R16 expected | capture says | verdict |
|---|---|---|---|
| `issues_list` | `list_issues` | `list_issues` advertised, `readOnlyHint: true`, required `owner, repo`, optional `state ∈ {OPEN, CLOSED}` | **CONFIRMED** |
| `issues_close` | `update_issue(state=closed)` | **`update_issue` does not exist.** v1.12.2 consolidated issue create/update into **`issue_write`** (`method ∈ {create, update}`, `state ∈ {open, closed}`, `issue_number`) | **FALSIFIED as written — CORRECTED to `issue_write`** |
| `merge_main` ½ | `create_pull_request` | advertised; required `owner, repo, title, head, base` | **CONFIRMED** |
| `merge_main` ½ | `merge_pull_request` | advertised; required `owner, repo, pullNumber` | **CONFIRMED** |

**No pivot to the native-adapter fallback.** R16 part 2's falsification trigger is the CANDIDATE
being falsified — "unobtainable, no stdio transport, verbs missing". None of those hold: the image
pulls, it speaks stdio on the pinned revision, and every one of SUNIL's three landable operations
has a live verb behind it. What was falsified is R16's *annotation* of one expected binding, which
R16 itself anticipated in the same sentence ("Expected shape, to be **confirmed or corrected** at
capture").

That correction is the whole argument for part 3's naming law, made concrete on its first day:
SUNIL's operation is still `github_mcp.issues_close` — the permission row, the approval card and
the audit history do not move — and the vendor's rename from `update_issue` to `issue_write` is
absorbed by a one-line `server_tool:` binding. Had we renamed SUNIL's operations to the vendor's
verbs (R16's rejected alternative), this capture would already have been a breaking change to the
permission matrix.

**Two further findings the capture settles:**

1. **No branch-merge tool exists.** Of 45 advertised tools not one merges a branch into another
   branch; `merge_pull_request` is the only merge, and it takes a PR number. R16 part 3's
   composition is therefore not the fallback shape — it is the ONLY shape, confirmed empirically.
2. **`push_files` is still not a branch push**, exactly as R16 part 4 found on the dead server. It
   is an API content-commit. `push_branch` stays dormant (parcel step 5: "if the engine-enablement
   ADR has not landed, `push_branch` stays dormant and the parcel lands the other three operations
   without it; the parcel must not invent the push executor"). It has not landed.

---

## 1. `server_tool:` bindings — ADR-034 Amendment 1

The SA is authoring Amendment 1's text on `task/S3-docs`; at the time these rows were written that
branch carried no amendment (checked by `git fetch` — `origin/task/S3-docs` did not exist). The
rows below are therefore written to **R16 part 3's specification**, which is the binding
instruction; the ADR text follows and must be read against them.

What landed in code:

* `config/tools.yaml` operations may carry `server_tool:` — a string (one bound tool) or a list
  (an ordered composition). **Default = the operation name**, so every existing row keeps its
  meaning and `n8n_mcp.post_update` needs no edit.
* The ADR-034 **drift check verifies the BINDINGS**, not the operation names: every bound server
  tool must be advertised by the live server or `start()` refuses and the whole tool leaves the
  registry. For a composition that means BOTH tools (R16 part 3, verbatim).
* **Invocation uses the binding.** `tools/call` is sent with the bound name.
* An operation may declare `fixed_arguments:` — constants the ADAPTER supplies and a plan cannot
  (`issues_close` → `{method: update, state: closed}`). The loader **refuses a fixed argument whose
  key collides with a field of the operation's `params_model`**, because the `args_hash` an
  approval binds to is computed over the params model: a fixed argument that could overwrite
  `issue_number` would make "the owner approved closing issue 42" false.

## 2. The composed `merge_main`

ONE governed operation, ONE permission row, ONE approval binding — exactly
`{project_key, branch, base_branch}`, unchanged from `MergeMainParams`. Inside the approved
execution:

1. `create_pull_request(owner, repo, title, head=branch, base=base_branch)`
2. read the PR number out of **that call's own result** — derived state, minted inside the approved
   execution, never a plan input and never a field of any params model
3. `merge_pull_request(owner, repo, pullNumber=<derived>)`

`owner`/`repo` are resolved from `config/projects.yaml` by the wiring code, exactly as the native
`github` tool resolves them (M1's T-16 rule): a plan names a `project_key` and never a repository.
A composition is CODE, not configuration — `sunil/tools/mcp/compositions.py`, dispatched by name,
the same reason `wiring._native()` gives for native tools. Config names WHICH composition; the
composition declares which server tools it needs; the loader refuses a `server_tool:` list that
does not match. Step 1 failing means step 2 never runs and the operation reports
`upstream_error`; a half-done merge is not possible because step 2 is the only thing that merges.

R16 called the composition "not a workaround, an upgrade": the owner's C4 decision now leaves a
server-side reviewable PR trail instead of a silent fast-forward.

## 3. Config rows

Restored from the dormant comment block **verbatim minus `push_branch`**, which stays dormant with
its own note pending the engine-enablement ADR (R16 part 4 + parcel step 5). `tools.yaml` gains the
`command:`/`version:` of the digest-pinned artefact above and the bindings from the capture;
`permissions.yaml` restores `project_manager.{issues_list: allow, issues_close: ask_user}` and
`developer.{merge_main: ask_user}`.

`developer.push_branch: allow` is NOT restored — so the parcel lands **no new unattended write**,
and `test_the_only_unattended_write_is_the_developers_push_branch`'s dormant-era successor stays
true: the set of `allow` grants on `read_only: false` operations is still empty.

## 4. Tests

| module | disposition |
|---|---|
| `tests/unit/github_mcp/test_recorded_handshake.py` | NEW — the transcription pin. Replays the verbatim capture through the real `McpToolAdapter`, real drift check, real binding resolution, built from the REPOSITORY's own `config/tools.yaml` block |
| `tests/unit/agents/test_developer_mount.py` | reverted to live-state pins (`merge_main` present and `ask_user`; `push_branch` still dormant) |
| `tests/unit/test_real_seams.py` | `github_mcp` back in both set assertions; the whole-set operations pin restored to the three landed operations |
| `tests/unit/core/permissions/test_engine.py` | the grant assertions flip back off `is None` for the three landed rows; `push_branch` stays `is None` |
| `tests/unit/core/tool_framework/test_tools_config.py` | the shipped-config test carries the three live adapter kinds again |
| `tests/unit/policies/test_non_tool_actions_never_become_tools.py` | NEW, standalone — QA F-1's catalogue-wide `fix_and_pr` scan re-landed as its own module so it survives future rewrites of any mount module |

## 5. Live smoke

See §5 below (appended after the run).

## 6. Verification round (2026-09-18)

The parcel's three commits were authored across sessions that did not survive to verify their own
claims end to end. This section is that verification, run against the pushed tip, and it is
deliberately kept separate from the claims it checks.

### 6.1 Ground truth — the commits exist and are pushed

| commit | subject | state |
|---|---|---|
| `711f08e` | ADR-034 Amendment 1: `server_tool:` bindings + the bounded `merge_main` composition | on `origin/task/S3-github` |
| `7d65b85` | `github_mcp` re-landed — capture gate passed, rows restored minus `push_branch` | on `origin/task/S3-github` |
| `6e4cd92` | the transcription pin + QA F-1's catalogue-wide scan, standalone | tip; `origin` == `HEAD` |

`git rev-list --left-right --count origin/task/S3-github...HEAD` → `0	0`; working tree clean. The
parcel is landed, not half-written.

### 6.2 Suite — SQLite leg

```
$ .venv/Scripts/python -m pytest tests -q      # apps/api, Python 3.13.14, SQLAlchemy 2.0.54
1170 collected
1123 passed, 47 skipped, 5 warnings in 23.28s
```

**1123 / 47** — identical to the count `6e4cd92`'s message claims. No failures, no errors. The five
warnings are the pre-existing httpx/anyio/pytest-asyncio deprecations carried by the branch point;
this parcel adds none.

### 6.3 The verification table — R16's parcel and ADR-034 Amendment 1, item by item

ADR-034 Amendment 1 is now merged on `origin/task/S3-docs` (`59b3ac2`, 2026-09-17). It was read
back against the code **after** the code landed — §1 of this file was written to R16 part 3's
specification while the amendment did not yet exist, so this row-by-row check is the first time
instrument and implementation have been compared.

| # | Required by | Claim | Verified how | Verdict |
|---|---|---|---|---|
| 1 | R16 part 2 / parcel step 0 | the verbatim capture exists as an artefact | `apps/api/tests/unit/github_mcp/fixtures/github_mcp_server_v1_12_2.json`, 177 899 bytes | **PASS** |
| 2 | R16 part 2 / parcel step 0 | a test **replays** it through the real adapter | `test_recorded_handshake.py` — 14 tests, all green. Includes `test_the_capture_is_the_artefact_the_config_pins` (provenance: the recording is of the digest `config/tools.yaml` spawns, not some other build) and `test_the_capture_carries_no_credential` | **PASS** |
| 3 | Am.1 point 2 | `server_tool:` binding, default = operation name | `config/tools.yaml`: `issues_list → list_issues`, `issues_close → issue_write`; `n8n_mcp.post_update` carries no binding and is unchanged | **PASS** |
| 4 | Am.1 point 2 | fixed arguments are adapter-side and cannot collide with a params field | `issues_close` carries `fixed_arguments: {method: update, state: closed}`; loader refusal covered by `test_mcp_server_tool_bindings.py` | **PASS** |
| 5 | Am.1 point 3 | composed `merge_main`, ONE operation, ONE approval over `{project_key, branch, base_branch}`, PR number derived | `server_tool: [create_pull_request, merge_pull_request]` + `composition: merge_via_pull_request`; `test_mcp_merge_main_composition.py` + `test_merge_main_composes_over_the_recorded_server` | **PASS** |
| 6 | Am.1 points 2–3 | the drift check verifies the **bindings**, and for a composition **every** listed tool | `adapter.py:155 _drift_check` iterates `config.server_tools`; `test_dropping_any_one_bound_verb_takes_the_whole_tool_out` is parameterised over all four verbs — dropping either half of the composition takes the whole tool out of the registry | **PASS** |
| 7 | Am.1 point 3 | a composition cannot reach a tool the drift check never verified | `adapter.py:231 call_server_tool` asserts against `_bound_server_tools` before `tools/call` | **PASS** |
| 8 | parcel step 4 | permission rows restored **minus** `push_branch` | `permissions.yaml`: `project_manager.github_mcp {issues_list: allow, issues_close: ask_user}`, `developer.github_mcp {merge_main: ask_user}`. `push_branch: allow` absent → the parcel adds no new unattended write | **PASS** |
| 9 | R16 part 4 / parcel step 5 | `push_branch` dormant **with its own note** | `config/tools.yaml:96-109` (restore recipe verbatim, engine-enablement ADR named) and `config/permissions.yaml:65-71`. `PushBranchParams` still in the tree (R15 precedent) | **PASS** |
| 10 | parcel step 4 | the four named test modules reverted to live-state assertions | `test_developer_mount.py` (three referenced operations; `push_branch` absent from config **and** `is None` in the matrix), `test_real_seams.py:159` (whole-set pin = the three landed operations), `test_engine.py`, `test_tools_config.py` — all green in the full run | **PASS** |
| 11 | QA F-1 | the scan is **standalone** | `apps/api/tests/unit/policies/test_non_tool_actions_never_become_tools.py`, its own package, independent of any mount module | **PASS** |
| 12 | QA F-1 | the scan **bites** | **Mutation run, this round.** A `fix_and_pr` operation was added to the `github_mcp` block of `config/tools.yaml` → `test_no_tool_in_the_whole_catalogue_exposes_it[fix_and_pr]` **FAILED** (`assert 'fix_and_pr' not in {'fix_and_pr', 'issues_close', 'issues_list', 'list_recent_activity', 'merge_main', 'post_update'}`), naming the ruling in the assertion message. Mutation reverted (`git checkout --`); module back to 5 passed, tree clean | **PASS — proven, not asserted** |

One discrepancy worth stating plainly, because it is the parcel's whole point: R16 part 2 and
Amendment 1 point 2 both illustrate the binding with `issues_close → update_issue`. The capture
falsified that verb and the code binds `issue_write`. This is not drift between instrument and
implementation — both documents flag the binding as the thing that absorbs exactly this, and R16
said "confirmed or corrected at capture". It is pinned so it cannot quietly revert
(`test_r16s_expected_binding_for_issues_close_is_falsified_by_the_capture`). The amendment's
illustrative example remains as written; SA may annotate it at leisure.

### 6.4 Postgres leg — **NOT RUN, environment-blocked**

Stated plainly rather than quietly skipped. The blessed pattern (a throwaway `postgres:17` on a
loopback-published port with a CSPRNG password, `docs/tasks/qa-wave-w1.md` §1) needs a Docker
daemon, and this host has none available to an unelevated session:

```
$ docker info
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine:
  open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
$ wsl --list --verbose
  docker-desktop    Stopped    2
$ Get-Service com.docker.service        → Stopped (StartType Manual)
$ Start-Service com.docker.service
  FAILED: Cannot open com.docker.service service on computer '.'      # needs Administrator
```

Docker Desktop was launched and left ~15 minutes; its WSL distro never came up because the
privileged helper service is stopped and starting it needs an interactive UAC elevation this
session cannot answer. **This is a host condition, not a parcel defect.**

What it does and does not cost: the parcel's own code is engine-agnostic — the `github_mcp` work
touches `config/*.yaml`, `tools/mcp/*` and tests, and adds no model, migration, query or
transaction. The engine-parametrised tests that would gain a `[postgresql+psycopg]` leg are the
pre-existing CAS/transaction proofs, unmodified by these commits. **Owner action:** run the leg on
a host with Docker before the merge record closes, and record the counts here.

### 6.5 Live smoke — the C4 park is PROVEN; the live read is **blocked by the same daemon**

Run 2026-09-18 through the REAL pipeline, nothing faked: adapters built by
`sunil.api.wiring.build_tool_registry` from this repository's own `config/tools.yaml`, the real
`PermissionEngineHook` over its own `config/permissions.yaml`, the real `DatabaseApprovalsService`,
the real `DbToolAuditHook`, the real `ToolManager` with `TransactionalApprovals`. The credential was
read from `C:\repo\SUNIL\.env` into the process environment only; the runner scrubs the value from
every line it emits, and no artefact of the run is committed.

**Registry, at boot:**

```
adapters : ['github', 'github_mcp']
skipped  : ['n8n_mcp']            # credential unset on this host — C1 §5, absent not half-present
github_mcp operations: ['issues_close', 'issues_list', 'merge_main']
```

`github_mcp` is back in a real registry built from real config, carrying exactly the three landed
operations and no `push_branch`. That is §3's claim, observed rather than asserted.

**The read — `project_manager` / `github_mcp.issues_list`, grant `allow`:**

| | |
|---|---|
| permission decision | **`allow`**, from the real engine — recorded on the `tool_calls` row |
| params | validated against `IssuesListParams` **before** the decision (an earlier run with wrong params returned `invalid_params` and never reached the permission stage — the double-validation order, observed) |
| outcome | **`transport_error`** — `start()` raised `ToolAdapterStartupError: github_mcp: MCP startup failed (MCP server closed its stdout (the child died mid-call))`. The `docker run` child exits immediately because the daemon in §6.4 is unreachable |

So the call reached the real spawn and died at the host, not in SUNIL. Two things this still proves:
the operation is granted `allow` by the real engine, and an adapter that cannot start **executes
nothing** — the call returns `transport_error` and is audited, rather than half-working (C1 §5).
**What it does NOT prove, and no one should claim it does: a real GitHub API response has not been
observed through this chokepoint.** Owner action: re-run on a Docker-capable host.

**The write — `developer` / `github_mcp.merge_main`, grant `ask_user`: PARKED, not approved.**

```
result.ok         : False
result.error_kind : approval_required

--- the C4 approval row ---
  id        : apr-01M2T5BFZDRRQ5BAD4K32ZFK3B
  status    : pending
  agent_id  : developer
  tool.op   : github_mcp.merge_main
  args_hash : 484af8d1417866e105e62422748662e54b3d8522bc9ad91b336e84bc1e6ca040
  summary   : merge task/S3-github into V2

--- tool_calls ---
  github_mcp.issues_list  agent=project_manager  decision=allow     outcome=error  approval_id=None
  github_mcp.merge_main   agent=developer        decision=ask_user  outcome=error  approval_id=apr-01M2T5BFZDRRQ5BAD4K32ZFK3B
```

This half is **complete and independent of the daemon** — parking happens before execution, which is
the entire point of C4. The showcase operation is governed again: ONE approval, `pending`, over
exactly `{project_key, branch, base_branch}` (the `args_hash` covers those three and nothing else —
no PR number anywhere, because it does not exist until inside the approved execution). **It was
deliberately NOT approved.** The row is a throwaway SQLite file in the session scratchpad, not any
real environment.

### 6.6 Round summary

| sub-step | state |
|---|---|
| 1 — ground truth + full suite (SQLite) | **DONE** — 1123 P / 47 S, tree clean, all three commits pushed |
| 2 — R16 + ADR-034 Am.1 verification table | **DONE** — 12 rows, all PASS; F-1 proven to bite by mutation |
| 3 — Postgres leg | **BLOCKED** — no Docker daemon obtainable without elevation (§6.4) |
| 4 — live smoke | **PARTIAL** — C4 park proven end to end; live read blocked by the same daemon (§6.5) |

Two items carry forward to whoever reviews this, both environmental and both named above: the
Postgres leg and the live `list_issues`. Nothing in the parcel's code is waiting on either.

## Notes for the reviewer

* `GITHUB_TOKEN` stays the single grantable GitHub credential name (`GRANTABLE_CREDENTIAL_NAMES`,
  condition C-3). The official server reads `GITHUB_PERSONAL_ACCESS_TOKEN`, so the `credential_env`
  → child-env NAME mapping is stated in `config/tools.yaml` and honoured by
  `credentials.build_child_env`. No second token field was added to `Settings`, and no secret value
  appears in config, argv or a log line.
* The 127 KB fixture is deliberately verbatim. It is evidence, and a paraphrased capture would
  prove nothing that a hand-written double does not already prove.
