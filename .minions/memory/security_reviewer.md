# Memory — Security Reviewer (security_reviewer)

## Lessons

- [L-001 | 2026-08-17 | SUNIL M1 T19] **LESSON:** I shipped two defective assertions in the
  original T19 suite — one **vacuous** (it called `.replace()` on the very delimiter it then
  checked for, so it could never fail) and one that conflated attacker text being *stored*
  with SUNIL *acting* on it (`tool_calls.result` legitimately contains the projected commit
  message; an audit trail omitting hostile input is worth less, not more). Neither surfaced
  until the pipeline existed to run them against.
  **ROOT CAUSE:** Writing them blind against a frozen contract was correct, but I then treated
  "red for the right reason" as evidence of correctness. **A test that has only ever failed
  because a module is absent has never exercised its own assertion logic.**
  **RULE:** An assertion is unverified until I have seen it fail *for the reason it exists*.
  When a feature lands, re-run every previously-blind test against it and mutation-test the
  control it guards. If a mutation does not kill the test, fix the test or state plainly that
  I could not certify it — never let a green stand as proof on its own.

- [L-002 | 2026-08-17 | SUNIL M1 ET-12] **LESSON:** Building a security harness on another
  lane's test scaffolding inherits that scaffolding's defects. I declined to build ET-12 on
  QA's `tests/exit/` fixtures; within the hour those fixtures were found to name an
  unregistered operation, which would have failed ET-12 for a reason with nothing to do with
  injection. **RULE:** A security assertion drives production wiring and fakes only genuinely
  external boundaries (the model provider, the remote HTTP API). Generate fixtures from the
  live schema builder rather than hand-copying literals, so the harness cannot drift.

## Conventions

- Findings are `file:line — blocker | should | nit`, with an explicit merge verdict. If a
  branch is clean, say so plainly — manufactured findings to look thorough are worse than none.
- Verify claims against the **merged tip**, not the branch that was reviewed. Several SHAs
  moved mid-review on this project; two "still absent" findings turned out to be fixed already.
- Withdraw a finding out loud when it proves wrong (one was retracted after tracing that the
  code scrubbed one line earlier). Noise degrades the signal the suite exists to protect.
- **A control that is claimed but not mechanised is a finding.** Applies to my own docstrings.
- Read-only by construction: deliver test code in the report; the Delivery Manager commits it
  with my authorship.

## Preferences

- The owner (Isuru) reads security reasoning and acts on it. His own review added ET-12 and
  forced the withdrawal of an "unforgeable" claim that Python could not support.
