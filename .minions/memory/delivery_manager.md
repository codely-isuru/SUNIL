# Memory — Delivery Manager (delivery_manager)

## Lessons

- [L-001 | 2026-08-13 | SUNIL V1 Stage 2] **LESSON:** I briefed the Business Analyst to
  `git add && commit && push` its own document. The BA role has **no shell tool by design**
  (Read/Glob/Grep/Write/Edit/WebSearch/WebFetch only), so the agent completed its work, then
  stalled at the commit step and had to hand the file back — costing a round trip on an ASAP
  timeline. **ROOT CAUSE:** I wrote the git-first instruction as a boilerplate paragraph for
  every dispatch instead of checking it against the role's own tool allowlist.
  **RULE:** Before adding a git instruction to a brief, check the role's tools. Shell-less roles
  (BA, Documentation, UI/UX, Graphic, Video, SEO, and Security Reviewer for writes) must be told
  "write the file and report the path — the Delivery Manager commits it". Only engineers, QA and
  DevOps commit their own work.

## Conventions

- Portal + git are synced at the same moment (`SKILL.md` §3a). Every blocker found by an agent is
  written into `docs/STATUS.md` known issues and pushed **before** the next task starts, not at
  close-out.
- Subagent commits and my own can race on `main`. Commit with **scoped paths**, never `git add -A`,
  while background agents are live.
- The Bash tool's cwd resets to the harness default between some calls on this machine; always
  `cd /c/repo/SUNIL &&` inside a compound command rather than trusting persisted cwd.
- Attribute the commit to the agent that authored the content (`git -c user.name=...`) even when
  I run the command, so authorship in git matches who did the work.

## Preferences

- Isuru (owner) chose: fresh start over retrofit, ASAP timeline, premium team, git-first.
  He answers structured confirm-or-correct questions fast; open-ended design questions stall.

## Lessons — M1 (2026-08-17)

- [L-002 | SUNIL M1] **LESSON:** I told BE-2 "you write the capture conversion, BE-1 deletes
  its duplicates" and separately told BE-1 "capture cleanup", **without naming the file**. Both
  created `sunil/capture.py` twelve minutes apart, diverging on a `ContentSource` member. Two
  correct engineers, one ambiguous instruction. **ROOT CAUSE:** I described work by topic where
  exclusive file ownership needed a path. **RULE:** When two lanes touch one concept, name the
  **file** and the **owner** in both briefs, not the task. Exclusive file ownership prevented
  every other cross-lane collision this milestone; the one failure was mine, not the rule's.

- [L-003 | SUNIL M1] **LESSON:** A branch is green against what it was cut from, not against
  what exists. Four instances: T5 carrying pre-fix redaction while its own tests passed; T8's
  merge-base resolving to a superseded T2 tip; T11a never having merged T3/T8/T10 at all
  (311 → 417 tests once it did); and T11b reporting 18 exit tests green on a branch where the
  same suite failed on `main`. **RULE:** Before accepting "green", ask what the branch was cut
  from. Require a merge-base check and a re-run against the current tip as part of done — and
  **run the suite on the trunk myself** before reporting a milestone state to the human. The
  fourth instance was caught only because I did.

- [L-004 | SUNIL M1] **LESSON:** I misattributed a `SecretStr` finding to T11a; `git blame` put
  it in a T5 commit predating that branch. The agent checked, showed the blame, and routed it
  back rather than editing another lane's file to be helpful. **RULE:** Attribute findings with
  `git blame`, not with proximity to the branch that surfaced them. An agent correcting me with
  evidence is the system working.

## Conventions — added at M1

- Every portal sync point is a git sync point, and a blocker found by any agent is written into
  `docs/STATUS.md` and pushed **before** the next task starts.
- Brief shell-less roles (BA, Design, Security) to report a path; the DM commits with their
  authorship. Check the role's tool allowlist before writing a git instruction into a brief.
- Merge order follows dependency order, and the DM merges — never the author. Where a merge
  conflicts non-trivially, hand resolution to the engineer owning **both** sides rather than
  improvising at the merge point; `settings.py` conflicted four times and was a union each time.
- Rule quickly and in writing when two lanes disagree. Every ruling this milestone that took
  more than one message cost a lane idle time.
