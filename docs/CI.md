# CI (T21) — what each job does, and how to reproduce it locally

**Owner:** OPS lane. **Workflow file:** `.github/workflows/ci.yml`. **Gates every merge**
(`docs/GIT_WORKFLOW.md` rule 4, `docs/M1_BUILD_PLAN.md` §5 T21) — Delivery Manager does not
merge a task branch until this is green.

**Target environment:** the workflow runs on GitHub-hosted `ubuntu-latest` (Linux) runners. That
is a different OS from this team's Windows 11 build machine. The commands below are written to be
byte-identical between the two, and every one of them uses `python`, never `python3` — on Linux
that would work either way, but this machine's `python3` is a broken Microsoft Store stub
(`docs/ENVIRONMENT.md` §1), so the workflow is written the way a developer must also type it here.

## Jobs

| Job | Runs | Skips cleanly when |
|---|---|---|
| `backend` | `pip install -e ".[dev]"` → `ruff check .` → `ruff format --check .` → `pytest -q -m "not live"` | never — `apps/api` exists from T1 |
| `frontend` | `pnpm install --frozen-lockfile` → `pnpm typecheck` → `pnpm build` | `apps/web/package.json` absent (T14 not merged yet) |
| `security` | `pytest apps/api/tests/security -q -m "not live"` | `apps/api/tests/security/` absent (T19 not merged yet) |

All three jobs run on every `push` and `pull_request`.

## No secrets, anywhere

- No `ANTHROPIC_API_KEY` / `GITHUB_TOKEN` GitHub Actions **secret** is referenced.
- The workflow's top-level `env:` block sets **obviously fake** literal values (e.g.
  `sk-ant-fake-ci-value`) for the required settings fields, so `sunil.settings.Settings()` /
  `sunil.main.create_app()` can construct in any test process that hasn't monkeypatched its own
  environment — mirroring `apps/api/tests/unit/test_settings.py`'s fixture. These are not
  credentials; they do not work against any real service.
- `.env` is never created, read, echoed, or uploaded as an artefact by CI.
- Tests that need a real credential are marked `@pytest.mark.live` and deselected here with
  `-m "not live"`.

## The pytest exit-5 trap

`pytest` exits **5** when it collects zero tests — a naive job that only checks for exit code
`1` (test failures) reports that as **green**. Both the `backend` and `security` jobs capture the
exit code explicitly and treat `5` as a failure:

```bash
set +e
python -m pytest -q -m "not live"
code=$?
set -e
if [ "$code" -eq 5 ]; then
  echo "::error::pytest collected zero tests (exit code 5). Empty is not green."
  exit 1
fi
exit "$code"
```

T1 shipped `apps/api/tests/unit/test_settings.py` specifically so this can never be hit by
accident on the real suite — this is a deliberate, tested control, not a hypothetical.

## Reproducing the `backend` job locally (Windows, PowerShell)

```powershell
cd apps\api
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m pytest -q -m "not live"
```

`scripts\dev-api.ps1` does the venv-creation and install steps for you as part of bringing the
API up for local development.

## Reproducing the `frontend` job locally

Only once `apps/web` exists (T14):

```powershell
cd apps\web
pnpm install --frozen-lockfile
pnpm typecheck
pnpm build
```

## Reproducing the `security` job locally

Only once `apps/api/tests/security` exists (T19):

```powershell
cd apps\api
.\.venv\Scripts\python.exe -m pytest tests\security -q -m "not live"
```

## Why the frontend/security "skip cleanly" checks are step-level, not a job-level `if:`

The build plan's own wording (`M1_BUILD_PLAN.md` §5 T21) suggests
`if: hashFiles('apps/web/package.json') != ''` at the job level. That condition is evaluated
**before any step in the job runs — including `actions/checkout`** — so at evaluation time the
runner's workspace is empty regardless of what exists in the repository, and `hashFiles()` would
not reliably reflect the real repo state. This workflow instead checks out the repo first, then
uses a step with an `id:` to test for the file/directory's existence and gates every later step
in the job on that step's output (`steps.web.outputs.present == 'true'` /
`steps.sec.outputs.present == 'true'`). The effect is identical to the plan's intent — the job
goes green with nothing to do rather than failing red — but it actually works.

## What CI cannot enforce — needs a human/process rule instead

- **No self-merges and no direct commits to `main`.** CI validates a branch; it does not stop
  someone from pushing straight to `main` or merging their own work. `docs/GIT_WORKFLOW.md` rules
  1 and 5 are the enforcement mechanism, and they are procedural, not technical, in this
  repository (no branch-protection API access was exercised as part of T21). If GitHub branch
  protection (required status checks, required reviewers, no direct pushes) is available to this
  repo, turning it on converts these from human rules into enforced ones — recommended, but out of
  T21's scope as specified.
- **Merge order following dependency order** (a stacked branch is never merged before its base) —
  CI has no concept of the task dependency graph in `M1_BUILD_PLAN.md` §1; only the Delivery
  Manager tracking that manually (or a future check reading `docs/tasks/*` metadata) enforces it.
- **Rebase-not-merge and `--no-ff` at merge time** — these are `git` invocation choices the
  Delivery Manager makes by hand; nothing in the workflow inspects how a merge commit was made.
- **"A test is never weakened, skipped or deleted to make it pass"** — CI can only tell you the
  suite that exists is green; it cannot tell you whether yesterday's suite was quietly made
  smaller. That is a review-time judgement (QA/Security reading the diff), not a CI check.
- **Announcing "green" in the Delivery Manager's thread** when a dependency branch becomes
  consumable (§0.1 rule 2) — a purely communication step; CI has no thread to post to.
