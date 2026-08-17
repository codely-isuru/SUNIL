# 2026-08-17 — M1's vertical slice is built, merged and green

**Team:** Minions Team 18 · **Stages 3–6** · `main` @ `0d16666`

## What shipped

```
513 passed, 0 failed, 6 deselected (live-credential only)
 18 passed — tests/exit, ET-1 … ET-12
 60 passed — tests/security, zero red
```

`POST /api/v1/chat` runs the roadmap §22 path end to end: chat → conversation gateway →
orchestrator → validated structured plan → Project Manager agent → read-only GitHub tool →
analysis → response, with all twelve NFR-020 trace stages emitted in order and
reconstructable from `audit_events` alone.

**Twenty-two tasks across seven lanes**, every one independently reviewed before merge, no
agent merging its own work.

## The three gates

| Gate | Outcome |
|---|---|
| 1 — scope and requirements | Approved as-is, all seven recommended defaults accepted |
| 2 — architecture | Approved after the owner's own written review (9/10 and 7.5/10) forced eleven corrections |
| 3 — production | **Not reached, and not ours.** Autonomy stops at staging. |

The owner's Gate 2 review is the single highest-leverage document of the milestone. It
corrected the critical path (T6/T8/T9/T10 were wrongly described as slack), replaced
concurrent direct-to-`main` commits with branches and worktrees, forced the withdrawal of an
"unforgeable" claim Python cannot support, and added **ET-12** — the prompt-injection control
that turned out to be the only M1 control with no exit test behind it.

## What the process actually caught

Defects found by review that no single lane could have seen:

* `scrub()` dispatched on a fixed type list with a silent passthrough, so an exception object
  logged as an ordinary structlog kwarg leaked a secret into both logs and the persisted
  `audit_events` table.
* A failed `Settings()` construction published every already-loaded secret in clear — the one
  path redaction cannot rescue, in a **public** repository.
* Two lanes independently created `sunil/capture.py` (a Delivery Manager instruction defect).
* `main` was once merged "clean" while a conftest import aborted a whole suite's collection.
* Four separate instances of a branch being green against what it was cut from rather than
  against what exists.

Two agents found defects in **their own** work and reported them rather than quietly fixing:
the Security Reviewer's vacuous ET-12 assertion (it stripped the delimiter it then checked
for, so it could never fail), and QA's fixture naming an operation the registry does not
register — copied from a stale worked example in the architecture document.

## What is left of M1

Six tests, all needing the owner's credentials (`docs/SECRETS_SETUP.md`): two live end-to-end
exit tests, and four verifying the GitHub PAT is genuinely read-only and single-repository.
That last group matters — the threat model rates PAT scope *mitigated* on the grounds that
provisioning is the owner's action, and provisioning is not verification.

Carry-forward items are in `docs/STATUS.md` §3a.
