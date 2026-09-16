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

## Notes for the reviewer

* `GITHUB_TOKEN` stays the single grantable GitHub credential name (`GRANTABLE_CREDENTIAL_NAMES`,
  condition C-3). The official server reads `GITHUB_PERSONAL_ACCESS_TOKEN`, so the `credential_env`
  → child-env NAME mapping is stated in `config/tools.yaml` and honoured by
  `credentials.build_child_env`. No second token field was added to `Settings`, and no secret value
  appears in config, argv or a log line.
* The 127 KB fixture is deliberately verbatim. It is evidence, and a paraphrased capture would
  prove nothing that a hand-written double does not already prove.
