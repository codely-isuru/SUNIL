# Git workflow — how work reaches `main`

**Status:** In force from 2026-08-14, for M1 onward.
**Origin:** the owner's architecture review, §5 — *"No autonomous implementation agent should
directly commit to shared `main` while other agents are running concurrently."*
**Owner of this document:** Delivery Manager.

## Why this exists

The first cut of the M1 build plan let several agents commit straight to `main` at once, relying
on strict per-task file ownership to keep them apart. File ownership prevents two agents editing
the same *file*. It does not protect *repository state*: concurrent commits, rebases and pushes
against one branch produce interleaved history, rejected pushes, and rebases that silently
reorder someone else's work. During Stage 3 this repo already saw one push rejected for exactly
that reason, with only two writers active. M1 runs five lanes.

So: shared `main` is a **merge target**, never a working surface.

## The model

```text
main  ← the only long-lived branch. Always green. Never committed to directly.
 │
 ├── task/T1-foundation
 ├── task/T3-registries
 ├── task/T6-model-router
 ├── task/T14-web-foundation
 ├── task/T18-qa-exit-tests
 └── task/T19-security-tests
```

One branch per task, named `task/T<n>-<slug>`. It is created from current `main`, carries only
that task's work, and is deleted after merge.

### Worktrees for the parallel lanes

Each concurrent lane gets its own checkout so lanes never fight over the working directory:

```text
C:\repo\SUNIL\                 ← main, the integration checkout (Delivery Manager only)
C:\repo\SUNIL-wt\be-core\      ← backend lane 1  (T1, T2, T4, T5, T9, T11)
C:\repo\SUNIL-wt\be-integr\    ← backend lane 2  (T3, T6, T7, T8, T10)
C:\repo\SUNIL-wt\frontend\     ← frontend lane   (T14, T15, T16)
C:\repo\SUNIL-wt\qa\           ← QA lane         (T18)
C:\repo\SUNIL-wt\security\     ← security lane   (T19)
C:\repo\SUNIL-wt\ops\          ← devops lane     (T17, CI)
```

Create one with:

```bash
git worktree add ../SUNIL-wt/be-core -b task/T1-foundation main
```

Worktrees share one object store, so this is cheap — no re-clone, and every branch is visible
from every worktree. `.venv/` and `node_modules/` are per-worktree and gitignored.

## The rules

1. **Never commit to `main` from a lane.** If `git status` in your worktree says `On branch main`,
   stop and tell the Delivery Manager.
2. **One task, one branch.** Do not stack unrelated work on a task branch.
3. **Rebase onto `main` before requesting merge** — `git fetch origin && git rebase origin/main`.
   Resolve conflicts in your own branch, never in `main`.
4. **CI must be green before merge.** Backend `ruff` + `pytest`; frontend typecheck + build;
   security import-boundary and critical security tests. A red lane does not merge, and a test is
   never weakened, skipped or deleted to make it pass.
5. **No agent merges its own work.** The Delivery Manager performs the merge after QA and, where
   in scope, Security have reviewed. This is a Minions hard rule, not a local preference.
6. **Merge is `--no-ff`**, so each task keeps an identifiable merge commit and can be reverted as
   a unit.
7. **Push your branch often.** An unpushed branch is invisible to the rest of the team and to the
   other machines this repo is worked from. Never end a session with unpushed work — commit
   unfinished work as `wip(T<n>): <done / not done>` and push anyway.
8. **Commit attribution stays honest.** The agent that wrote the content is the commit author,
   even when the Delivery Manager runs the command on its behalf (roles without shell access).

## Merge sequence, per task

```text
lane finishes task
   ↓  push task/T<n>-…
QA runs the task's acceptance + exit tests against that branch
   ↓  findings land in docs/tasks/T<n>.md as file:line — blocker|should|nit
Security reviews (where the task touches auth, permissions, tools, secrets or external content)
   ↓  blockers bounce to the same engineer, with a lesson written after the fix
CI green
   ↓
Delivery Manager merges --no-ff to main, deletes the branch, updates docs/STATUS.md, pushes
```

## What still goes straight to `main`

Documentation and delivery bookkeeping written by the Delivery Manager — `docs/STATUS.md`,
worklog entries, task files, ADR-000 — when no merge is in flight. These touch no code and
no lane depends on them.

## Cleaning up

```bash
git worktree remove ../SUNIL-wt/be-core
git worktree prune
git branch -d task/T1-foundation
```

Worktrees left behind after M1 are stale checkouts of a moved target — remove them at milestone
close-out.
