# integration-w2r2 — applying the cross-owner deltas on the merged tree

**Branch:** `task/integration-w2r2` (C + E + F merged) · **Lane:** backend_engineer · **Date:** 2026-09-12
**Scope:** the items streams C/E/F recorded as owed to other lanes, the frictions the merge exposed,
and a full-tree proof. Docs untouched except this file and `docs/ENVIRONMENT.md` §9 (assigned).

---

## 1. Disposition, item by item

| # | Item | Owner who recorded it | Disposition |
|---|---|---|---|
| 1a | `.env.example` `SUNIL_N8N_MCP_BASE_URL` → `http://localhost:5680/mcp/sunil` | E §7.1 | **APPLIED** |
| 1b | compose api-stub → `http://n8n:5678/mcp/sunil` | E §7.1 | **APPLIED** |
| 1c | ADR-033 passes unchanged | E §7.1 | **VERIFIED** through the real validator, both values |
| 2a | `permissions.yaml`: `developer.github_mcp` push_branch `allow`, merge_main `ask_user` | F §5.1 | **APPLIED** verbatim |
| 2b | `tools.yaml`: `github_mcp` exposes both, `read_only: false`, params `{project_key, branch, base_branch}` | F §5.2 | **APPLIED** — extended the existing block; two new `extra="forbid"` models |
| 2c | `settings.py`: `SUNIL_OPENHANDS_BASE_URL` + `openhands` in the named-host set | F §5.3 | **APPLIED** — set lives in `settings.py::_NAMED_HOSTS`, keyed per field |
| 2d | `plan_schema.py`: `fix_and_pr` into `NON_TOOL_ACTIONS` | F §5.6 | **APPLIED** |
| 3 | C's out-of-list files (fence, `main.py`, `.env.example`) | C §7.7 | **VERIFIED on the merged tree**, empirically — §3 below |
| 4a | yamllint `config/agents.yaml:25` | E §6 | **FIXED** — the tree now lints with zero warnings |
| 4b | `.env.example` merge artefacts | brief | **NONE FOUND** — verified, §4 |
| 4c | stale-volume hint in `ENVIRONMENT.md` §9 | E §7.3 | **APPLIED** |
| 5 | full-tree proof | brief | §5 |

Items 2c and 1a/1b were ratified by the SA mid-round as **ADR-033 Amendment 1** (rulings R14/R15,
commit `1af8112`), which also names the integration engineer as the applier and gives the default
`http://localhost:3400`. The `settings.py` default for the n8n URL moved with it, because
`ARCHITECTURE_V2.md` §5's inventory row — which `tests/unit/test_settings.py` asserts against —
now carries `/mcp/sunil`.

**Not applied, deliberately:** `openhands` was NOT added to `providers/registry.py::NAMED_GATEWAY_HOSTS`
(gateway-scoped: only `litellm` is admissible there) or `core/approvals/notify.py::NAMED_HOSTS`
(the approval-webhook set). A test now pins that non-widening: `openhands` is refused on the
gateway, n8n and webhook fields.

---

## 2. What was written, and the red step for each

Every behaviour change had a failing test first; the RED count is stated because "the test passes"
is not evidence unless it could have failed.

| Test | RED how |
|---|---|
| `tests/unit/test_env_template_parity.py` (new, 9) | 2 red: both committed n8n URLs still said `/mcp`. The other 7 are guards on properties that already held — the template's single-assignment rule and its `Settings` coverage — and the coverage guard then went red on its own when `sunil_openhands_base_url` landed without a template row, which is the guard working rather than a test written to pass |
| `tests/unit/agents/test_developer_mount.py` (new, 12) | 7 red before the two config rows existed (`KeyError` / `DENY` / "agents.yaml grants developer github_mcp.push_branch, which config/tools.yaml does not expose"). Mutation-checked afterwards by flipping `merge_main` to `allow`: 2 red, reverted |
| `tests/unit/test_settings.py` (+9) | 8 red: the openhands field did not exist, and the n8n inventory default was the old path |
| `tests/unit/test_plan_validation.py` (+2) | 1 red: `assert 'fix_and_pr' in ('resolve_project', 'summarise_activity', 'answer')`. The layer-4 test passed immediately — exactly as F predicted, layer 4 does not constrain `action` on a non-tool step — and is kept because it is what shows layers 1 and 4 agree |

Two **growth-pinned tests moved with the config they pin**, which is the mechanism working:
`tests/unit/test_real_seams.py` asserts `github_mcp`'s operation set whole, and
`tests/unit/core/permissions/test_engine.py` asserts the agent list whole.

That second one carried a claim worth recording: its docstring said "nothing is granted `allow`
that is not read-only". It never asserted that, and ADR-030 §4 makes it false —
`developer.github_mcp.push_branch` is an unattended write, deliberately. The prose is now an
**enforced** test instead: `test_the_only_unattended_write_in_the_matrix_is_the_developers_branch_push`
checks every `allow` row in the whole matrix against `read_only` in `config/tools.yaml` and admits
exactly one named exception, so the next one trips it.

---

## 3. Stream C's out-of-list files, verified rather than assumed

* **`sunil/db/autogenerate.py`** — the fence holds all six tables (`approvals` + C's five).
  Probed against a throwaway pgvector container at head `0005`:
  `alembic revision --autogenerate` produced a migration whose `upgrade()` and `downgrade()` are
  both `pass`. **Mutation check:** emptying `FENCED_TABLES` and re-running the same probe emitted
  `op.drop_table` for `memories`, `memory_entity_links`, `people`, `projects`, `clients` and
  `approvals` (plus every index, including the HNSW one). Restored byte-for-byte.
* **`sunil/main.py`** — the application engine is passed to the memory seam
  (`resolve_memory_provider(settings, seams, engine=read_engine)`), so the provider files a memory
  into the same database its audit row goes to.
* **`.env.example`** — `SUNIL_MEMORY_PROVIDER=pgvector` plus the three embedding rows, present and
  correct.

**Fresh deploy**, empty database → `alembic upgrade head` → `alembic current` = `0005 (head)`;
`alembic heads` shows a **single** head. Tables after: `alembic_version approvals audit_events
clients conversations llm_calls memories memory_entity_links messages people plans projects
task_status_events tasks tool_calls users`.

---

## 4. `.env.example` after three lanes edited it

Read whole. **No merge artefacts:** every key is assigned exactly once (now asserted by a test —
dotenv keeps the LAST assignment, so a duplicate is a silent last-one-wins that a reviewer reading
the top of the file cannot see). Section order is intact and each new block sits with its subject.

Checked both directions against `ARCHITECTURE_V2.md` §5:

* every `Settings` field has a template row, except the four the template itself excludes on the
  record (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY` and their base URLs — scoped to the LiteLLM
  container so the application process never holds an upstream key). Both halves are now tests;
* every §5 inventory row has a template key, bar those same four and the
  `LITELLM_VIRTUAL_KEY_<AGENT_ID>` pattern.

One stale statement corrected while in the file: the `SUNIL_N8N_MCP_AUTH_TOKEN` comment still said
bearer enforcement was unverified and the endpoint "must be treated as unauthenticated". S2-E §4
settled that against the live 2.38.5 server; the note now says what the proof is bound to (the
export's `authentication: bearerAuth`, whose node default is `none`), because that is the part an
operator has to keep true.

---

## 5. Full-tree proof

| Gate | Result |
|---|---|
| Suite, SQLite leg, run 1 / run 2 | **1092 passed, 47 skipped** (both) |
| Suite, Postgres leg, run 1 / run 2 | **1184 passed, 4 skipped** (both) |
| Alembic fresh deploy on an empty database | `0005 (head)`, single head, 16 tables |
| Autogenerate at head 0005 | emits **nothing** (fence probe, §3) |
| `yamllint -c .yamllint.yml config/ infra/ .github/workflows/` | clean, **zero warnings** (was one) |
| compose refuses with NO env file | OK (fail-closed secret guard intact) |
| compose resolves against `.env.example` | OK — `postgres`, `n8n`, `litellm` |
| no unresolved variables in the resolved config | OK |
| every image pinned, no floating tag | OK (3 images) |
| port / loopback / ADR-032 parity, 4317 free | OK — `postgres:5433, litellm:4000, n8n:5680`, all `127.0.0.1` |
| secret scan of tracked files | OK — 430 files scanned, no hits |
| ASCII guard on executable scripts | OK — 7 scripts, all ASCII |

Baseline for comparison: the merged tree before this round was **1059 passed / 47 skipped**
(SQLite). The 47 skips are the unchanged pattern — 43 of Stream C's memory suite skip loudly
without `SUNIL_TEST_DATABASE_URL`, plus the 4 baseline skips that remain on the Postgres leg.
This round added **33** tests (12 + 9 + 9 + 2 + 1 parametrisation).

Throwaway Postgres, blessed pattern: `pgvector/pgvector:0.8.6-pg17` published on
`127.0.0.1:5436`, password generated into the environment and never written to the repository,
container and both databases discarded at the end.

---

## 6. Defects found this round

**D1 — OPEN, needs a ruling: `github_mcp`'s operation names are not the pinned server's.**
Probed the real `command:` on 2026-09-12. `@modelcontextprotocol/server-github@0.6.2` advertises
exactly nine tools: `create_branch, create_issue, create_or_update_file, create_pull_request,
create_repository, fork_repository, get_file_contents, push_files, search_repositories` — and npm
reports the package itself "no longer supported". **None** of SUNIL's four configured operations
(`issues_list`, `issues_close`, and now `push_branch`, `merge_main`) is in that list. ADR-034's
startup drift check refuses `start()` on a mismatch, and that refusal is not local to one row: the
entire `github_mcp` tool leaves the registry — Stream E's `run_workflow` lesson, one lane over.
Nothing in the suite catches it because no test spawns the server.
It **predates** this round's two rows (`issues_list`/`issues_close` have it too), so adding them
changed the blast radius not at all, and removing them would leave Stream F's seam unreachable.
Recorded in `config/tools.yaml` at the point of use. The fix is a choice — rename to the server's
verbs (there is no merge tool there at all), or pin a maintained server that publishes these —
and each option changes a params model, so it is the integration ruling's, not mine.

**D2 — FIXED: the compose api stub would have refused to boot.** It defaulted
`SUNIL_MEMORY_PROVIDER` to `mem0`; Stream C made `mem0` a loud `SeamUnavailable` (never a silent
fallback) and committed `pgvector` in `.env.example`. Any container whose `.env` omitted the
variable would have failed startup. Now `pgvector`, the ratified engine (ADR-030 Amendment 2).
Mechanical, and not Stream C's file to fix.

**D3 — FIXED: a false security statement in `.env.example`** (§4 above).

**D4 — FOR THE SA, one line: `ARCHITECTURE_V2.md` §5's `SUNIL_OPENHANDS_BASE_URL` row still reads
"**field not yet in `settings.py`**".** It is in `settings.py` as of this branch, with its
validator and its named-host entry. I am not touching `docs/ARCHITECTURE_V2.md` this round; the
flag needs clearing so the inventory does not carry a stale caveat into the next review.

**D5 — FIXED, recorded above:** the untrue "no `allow` on a write" claim in `test_engine.py`'s
docstring, replaced by an enforced repo-wide tripwire.

---

## 7. Files

| File | Change |
|---|---|
| `.env.example` | n8n MCP path, the auth-token note, new `SUNIL_OPENHANDS_BASE_URL` row |
| `infra/docker-compose.yml` | api-stub: n8n MCP path, `SUNIL_OPENHANDS_BASE_URL`, memory default `mem0` → `pgvector` |
| `config/tools.yaml` | `github_mcp` + `push_branch` / `merge_main`; the D1 defect note |
| `config/permissions.yaml` | the `developer` agent's two rows |
| `config/agents.yaml` | the over-long ruling comment wrapped (content unchanged) |
| `apps/api/sunil/settings.py` | `sunil_openhands_base_url` + validator + `_NAMED_HOSTS` entry; n8n default path |
| `apps/api/sunil/tools/mcp/params.py` | `PushBranchParams`, `MergeMainParams` |
| `apps/api/sunil/core/orchestrator/plan_schema.py` | `fix_and_pr` in `NON_TOOL_ACTIONS` |
| `apps/api/tests/unit/test_env_template_parity.py` | new (9) |
| `apps/api/tests/unit/agents/test_developer_mount.py` | new (12) |
| `apps/api/tests/unit/test_settings.py` | +9, inventory default moved |
| `apps/api/tests/unit/test_plan_validation.py` | +2 |
| `apps/api/tests/unit/test_real_seams.py`, `tests/unit/core/permissions/test_engine.py` | growth pins moved with their config |
| `docs/ENVIRONMENT.md` | §9 first-boot: the stale `n8n_data` volume trap |
| `docs/tasks/integration-w2r2.md` | this file |
