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
