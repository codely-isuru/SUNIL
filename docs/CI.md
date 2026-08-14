# CI (T21/T22) — what each job does, and how to reproduce it locally

**Owner:** OPS lane. **Workflow file:** `.github/workflows/ci.yml`. **Gates every merge**
(`docs/GIT_WORKFLOW.md` rule 4, `docs/M1_BUILD_PLAN.md` §5 T21) — Delivery Manager does not
merge a task branch until this is green.

**T21** built the three jobs. **T22** hardened them after a real integration-only defect (see
"Cross-lane test-collection collisions" below) and a security review (see "T22 security review
findings" below). Both are folded into the same workflow file; this doc covers both.

**Target environment:** the workflow runs on GitHub-hosted `ubuntu-latest` (Linux) runners. That
is a different OS from this team's Windows 11 build machine. The commands below are written to be
byte-identical between the two, and every one of them uses `python`, never `python3` — on Linux
that would work either way, but this machine's `python3` is a broken Microsoft Store stub
(`docs/ENVIRONMENT.md` §1), so the workflow is written the way a developer must also type it here.

## Jobs

| Job | Runs | Skips cleanly when | Becomes mandatory when |
|---|---|---|---|
| `backend` | duplicate-basename check → `pip install -e ".[dev]"` → `ruff check .` → `ruff format --check .` → `pytest -q -m "not live"` | never — `apps/api` exists from T1 | always mandatory |
| `frontend` | `pnpm install --frozen-lockfile` → `pnpm typecheck` → `pnpm build` | `apps/web/package.json` absent | `FRONTEND_REQUIRED: "true"` is set (flip the moment T14 merges to `main`) |
| `security` | `pytest apps/api/tests/security -q -m "not live"` | `apps/api/tests/security/` absent | `SECURITY_SUITE_REQUIRED: "true"` is set (flip the moment T19 merges to `main`) |

All three jobs run on every `push` and `pull_request`.

## Repository visibility, and why it matters here

`codely-isuru/SUNIL` is **public**. Every workflow run's log is world-readable. That changes the
cost of a mistake: a CI job that ever holds a real credential and drops a variable into a log line
publishes it to the internet, not merely to the team. Two consequences, both already applied:

1. **No GitHub Actions secret is referenced anywhere in this file** — no `secrets.*`. The suite
   runs entirely against fake literal placeholders (below) and a local SQLite file.
2. **`permissions: contents: read`** is set at the workflow level. Nothing in these jobs writes to
   the repo, comments on a PR, or touches packages/deployments, so the default `GITHUB_TOKEN` needs
   nothing beyond read access — and that guarantee now lives in the reviewed file itself, not only
   in a repository setting a different admin could flip later.

## Fake settings values — present, but scoped to the steps that need them

`sunil.settings.Settings()` has several required (non-defaulted) fields, so anything that imports
`sunil.main` — including pytest collecting a test module that does so — needs *some* value for
`ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `SESSION_SECRET`, `OWNER_USERNAME`, `OWNER_PASSWORD` even in a
test process that hasn't monkeypatched its own environment (mirrors
`apps/api/tests/unit/test_settings.py`'s fixture values). These are **obviously-fake literal
strings** (e.g. `sk-ant-fake-ci-value`), never a credential, and:

- They are set only on the two `pytest` steps that actually need them (`backend`'s and
  `security`'s), **not** at job or workflow level.
- **Why that scoping matters (T22 security review finding 1):** `GITHUB_TOKEN` is a name that `gh`
  and many third-party actions read from the ambient environment. A workflow-wide fake
  `GITHUB_TOKEN` silently shadows the real one `actions/checkout` already provides via
  `github.token` — harmless today (nothing calls `gh` here), but the first `gh pr comment` or
  similar step anyone adds later would 401 with no obvious cause. Scoping the fake value to only
  the `run:` step that needs it removes that trap entirely without giving anything up.
- `.env` is never created, read, echoed, or uploaded as an artefact by CI.
- Tests that need a real credential are marked `@pytest.mark.live` and deselected here with
  `-m "not live"`.

## The pytest exit-code family — "empty is not green" generalised

`pytest`'s documented exit codes, and what each means for these jobs:

| Exit code | Meaning | This workflow's response |
|---|---|---|
| 0 | all collected tests passed | step passes |
| 1 | one or more tests failed | loud, explicit failure |
| 2 | collection or execution was **interrupted** | loud, explicit failure |
| 3 | internal pytest error | loud, explicit failure |
| 4 | command-line usage error | loud, explicit failure |
| 5 | **zero tests collected** | loud, explicit failure |

T21 originally special-cased only exit 5 (a naive job that checks only for exit code `1` reports a
zero-test run as green). **T22 generalises this to the whole family**, because exit **2** turned
out to be the one that actually bit the team (see the incident below) and a job that only reacts
to *some* nonzero codes with a real message, and others with silent nonzero propagation, is a job
half the team will misread under time pressure. Every non-zero/non-one code now gets its own
`::error::` line naming the failure class, not just a raw pytest exit code in the logs:

```bash
set +e
python -m pytest -q -m "not live"
code=$?
set -e

if [ "$code" -eq 0 ]; then
  exit 0
fi
if [ "$code" -eq 1 ]; then
  echo "::error::pytest reported one or more test failures (exit code 1)."
  exit 1
fi
if [ "$code" -eq 5 ]; then
  echo "::error::pytest collected zero tests (exit code 5). Empty is not green — treating as a failure."
  exit 1
fi
echo "::error::pytest aborted abnormally (exit code $code) — the collection-error family (e.g. two lanes shipping same-named test modules -> exit 2; internal errors -> exit 3; usage errors -> exit 4). This is never a pass."
exit 1
```

Independently verified by the Security Reviewer against the real workflow: the mapping is
`0→0, 1→1, 2→2, 4→4, 5→1` at the `pytest` level, and every one of those exits the CI step/job
non-zero — no path was found where a collection error reads as a pass.

T1 shipped `apps/api/tests/unit/test_settings.py` specifically so exit 5 can never be hit by
accident on the real suite — a deliberate, tested control, not a hypothetical.

## Cross-lane test-collection collisions — an integration-only defect class

**What happened (2026-08-14, during T22).** BE-2 built `task/T8-github-tool`'s base by merging
`origin/task/T7-permissions` into `origin/task/T4-trace-spine`. The merged tree failed to collect
*any* tests:

```
ERROR collecting tests/unit/test_capture.py
import file mismatch:
imported module 'test_capture' has this __file__ attribute:
  ...\tests\unit\registry\test_capture.py
which is not the same as the test file we want to collect:
  ...\tests\unit\test_capture.py
!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!
1 error in 0.68s
```

T2 shipped `apps/api/tests/unit/test_capture.py`; T3 shipped
`apps/api/tests/unit/registry/test_capture.py`. Neither test directory had an `__init__.py`, so
pytest's default ("prepend") import mode imports each test file by its bare module name — and two
files sharing a basename collide at import time, **aborting collection for the entire suite**
(exit code **2**). Each lane was 100% green in isolation; the collision only exists once the two
are merged, which is precisely the moment nobody is re-reading either lane's diff. Reproduced and
confirmed independently as part of T22 (exit code 2, `1 error during collection`, zero tests run).

**The fix that was tried and reverted, and why it matters.** `--import-mode=importlib` is the
conventional fix for exactly this collision, and BE-1 tried it first while independently hitting
the same collision merging T3 into T5's base. It was **reverted**: T3's registry tests use a bare
`from conftest import ...`, which relies on prepend mode's implicit `sys.path` insertion of the
test file's directory — `importlib` mode does not do that, so switching modes would have broken
62 passing tests to fix a naming collision. **The smaller, ownership-respecting fix was used
instead:** BE-1 renamed its own T2-owned file, `tests/unit/test_capture.py` →
`tests/unit/test_db_capture.py` (BE-1 owns both T2 and T5, so this is a lane renaming its own
earlier file, never another lane's). Full suite on that branch: **150 passed**, duplicate-basename
check clean (verified independently as part of T22 against `origin/task/T5-api-skeleton`).

**Lesson for whoever reaches for `--import-mode=importlib` next:** it is the textbook answer, and
it is not free here. Check what the colliding lane's tests assume about import mechanics before
switching modes for everyone.

**What T22 added so the *class* is caught, not just this one instance:**

1. **`scripts/check_test_basenames.py`** — a fast, dependency-free static check (no pip install
   needed) that walks `apps/api/tests/` for any basename appearing more than once, prints every
   colliding path, and exits 1. It runs as the **first** step of the `backend` job, before install
   or lint, so a colliding merge fails at the cheapest possible point with a message that names the
   exact files, rather than pytest's "import file mismatch" (which is correct but does not, by
   itself, say "two lanes collided").
2. **The exit-code-family handling above** — the general safety net. Even without the static
   check, exit code 2 now produces an explicit `::error::` naming the collection-error family, not
   a bare nonzero exit a reader has to go dig pytest's docs for.

**Why *not* a hardcoded minimum collected-test count** (considered and rejected, per the Delivery
Manager's ask to argue the call either way): with six lanes merging over a three-day build, any
fixed number is stale within hours of being written. Set it too low and it catches nothing; set it
to today's count and it false-fails the next legitimate smaller merge (e.g. a hotfix branch, or a
lane still mid-task); keep raising it by hand and it becomes a number nobody trusts or bothers to
update. A duplicate-basename scan has no such decay — it is exactly as correct on day one as on the
last day of the milestone, and it fails on the actual defect rather than on an arbitrary threshold.

## "Absent is green" — the other half of "empty is not green"

The Security Reviewer's third finding: the `frontend` and `security` jobs' skip-cleanly guards
were unconditional — they read "not present yet" as green **forever**, including after T14/T19
land. A later accidental deletion or rename of `apps/web` or `apps/api/tests/security` would
silently return the job to green, which is the same shape of silent-pass risk as the exit-5 trap,
arriving through a different door (module presence rather than test count).

**Fix:** each guard now checks a boolean env flag before treating absence as a skip:

```bash
if [ -f "apps/web/package.json" ]; then
  echo "present=true" >> "$GITHUB_OUTPUT"
elif [ "$FRONTEND_REQUIRED" = "true" ]; then
  echo "::error::apps/web/package.json is missing, but FRONTEND_REQUIRED=true. Treating as a failure."
  exit 1
else
  echo "present=false" >> "$GITHUB_OUTPUT"
fi
```

`FRONTEND_REQUIRED` and `SECURITY_SUITE_REQUIRED` both ship `"false"`. **Action item for whoever
merges T14 / T19 to `main`: flip the corresponding flag to `"true"` in the same PR (or immediately
after) that lands the directory.** This is a one-line, reviewable, auditable change — a diff that
flips `"false"` to `"true"` is exactly the kind of thing a reviewer notices, unlike a silently
permissive default that nobody ever revisits. It deliberately is **not** the same mechanism as the
duplicate-basename/minimum-count question above: that one is about *test collection health* inside
a tree that exists; this one is about *whether a whole subtree that used to be required is still
there at all*. Different failure shape, so a different, purpose-built guard — collapsing them into
one mechanism would have made both harder to read for no shared benefit.

## T22 security review findings — full disposition

The Security Reviewer's verdict on the workflow, recorded because it should be, not buried:
*"CI injection posture is excellent."* Zero `${{ }}` interpolations of untrusted input anywhere, no
`pull_request_target`, no `workflow_run`, no `secrets.*` reference, `.env` never created, read, or
uploaded, no artefact upload step at all. A malicious PR gets a restricted, read-only context with
nothing in it worth exfiltrating.

Three `should` findings, all addressed above:

1. Workflow-wide `GITHUB_TOKEN` shadowed the name `gh`/actions read from the ambient environment →
   scoped to only the two `pytest` steps that need it.
2. No `permissions:` block (not a live hole — the repo's default Actions token is already
   read-only with `can_approve_pull_request_reviews: false` — but the guarantee should live in the
   reviewed file, not only in a repository setting) → `permissions: contents: read` added at
   workflow level.
3. "Empty is not green" (exit-5 handling) was defeated by "absent is green" (the frontend/security
   skip guards never expiring) → the `*_REQUIRED` mandatory-flip pattern above.

One `nit`, left as-is by conscious choice: actions are tag-pinned (`@v4`/`@v5`) rather than
SHA-pinned. With a read-only token, no secrets, and no artefacts, the blast radius of a compromised
action here is low, and the reviewer agreed this is genuinely low-stakes in this specific workflow.
Revisit if a job ever gains write permissions or a real credential.

**A new consumer of the duplicate-basename/collection-error guards:** `origin/task/T19-security`
now carries `apps/api/tests/security/` (52 tests, a number of them red by design pending the rest
of T19's build). Its `require()` helper calls `pytest.fail`, never `pytest.skip`, on exactly the
reasoning in this document — a skipped security test reports green. Worth noting approvingly: T19
independently arrived at "skip reads as green, so don't skip" for its own internal assertions, the
same principle this file applies at the CI-job level.

## Reproducing the `backend` job locally (Windows, PowerShell)

```powershell
python scripts\check_test_basenames.py
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
  repository (no branch-protection API access was exercised as part of T21/T22). If GitHub branch
  protection (required status checks, required reviewers, no direct pushes) is available to this
  repo, turning it on converts these from human rules into enforced ones — recommended, but out of
  T21/T22's scope as specified.
- **Merge order following dependency order** (a stacked branch is never merged before its base) —
  CI has no concept of the task dependency graph in `M1_BUILD_PLAN.md` §1; only the Delivery
  Manager tracking that manually (or a future check reading `docs/tasks/*` metadata) enforces it.
- **Rebase-not-merge and `--no-ff` at merge time** — these are `git` invocation choices the
  Delivery Manager makes by hand; nothing in the workflow inspects how a merge commit was made.
- **"A test is never weakened, skipped or deleted to make it pass"** — CI can only tell you the
  suite that exists is green; it cannot tell you whether yesterday's suite was quietly made
  smaller. That is a review-time judgement (QA/Security reading the diff), not a CI check.
- **Flipping `FRONTEND_REQUIRED` / `SECURITY_SUITE_REQUIRED` when T14/T19 land** — CI cannot know
  "this task has now landed on `main`"; a human (Delivery Manager, at merge time) has to make that
  edit. Until it happens, a deleted `apps/web` or `apps/api/tests/security` still reads as a clean
  skip, not a failure.
- **Announcing "green" in the Delivery Manager's thread** when a dependency branch becomes
  consumable (§0.1 rule 2) — a purely communication step; CI has no thread to post to.
