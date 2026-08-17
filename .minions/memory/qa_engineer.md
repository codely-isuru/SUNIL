# Memory — QA Engineer (qa_engineer)

## Lessons

- [L-001 | 2026-08-17 | SUNIL M1 T18] **LESSON:** A test can be "red for the right reason"
  against my own branch while masking a second, deeper bug underneath it. My exit tests failed
  on a 404 (the chat route did not exist yet) — correct and expected — and that early failure
  short-circuited every request *before* layer-4 plan validation, hiding a wrong operation name
  in my own `_plans.py` fixture. It surfaced only once the route landed, costing an hour on the
  final day.
  **ROOT CAUSE:** I verified fixtures against my own branch, where an earlier-layer failure
  always fired first.
  **RULE:** Once a dependency I was blocked on lands, re-run the full suite against the **real
  integrated tip**, not my own branch, before declaring "red for the right reason" complete. A
  fix can be the trigger that reveals a second bug beneath it.

- [L-002 | 2026-08-17 | SUNIL M1] **LESSON:** The fixture bug came from copying a worked
  example out of `ARCHITECTURE_V1.md` that was stale against the shipping `config/tools.yaml`.
  **RULE:** Fixtures are derived from the artefact the application actually loads — the real
  config, the live schema builder — never from a document's illustrative example. Where a doc
  and the shipping config disagree, the config wins and the doc is a finding.

## Conventions

- **Scope every assertion to the run window** (`request_id`, timestamp window, fresh DB).
  Pre-existing rows are never evidence. Carried from `backend_engineer` L-002 and it has held.
- `require()` calls `pytest.fail`, never `pytest.skip` — a skipped security test reports green,
  which is CI's exit-code-5 silent pass in a different costume.
- Prove a red harness is red *for the right reason*: stand up a throwaway scaffold, watch the
  test advance to its next real blocker, then remove it.
- Review by **running** — extract the branch read-only (`git worktree add --detach`, not
  `git archive`, which breaks tests that shell out to git), run its own suite plus independent
  adversarial probes. Never review from a commit message.
- Fix the **class**, not the instance, where the cost is similar: an autouse fixture that
  snapshots and restores the stdlib logger registry beats renaming two colliding loggers.
- No Edit tool by design. Findings go back to the engineer; I never fix the code under test.

## Preferences

- Verify the coordinator's factual claims (SHAs, branch states, "blockers fixed") against git
  before acting. Several were stale. Being checked is welcomed here, not resented.
