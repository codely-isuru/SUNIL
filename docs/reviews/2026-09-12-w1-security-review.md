# Security Review — Wave 1 (integration-w1 → V2) · Minions Team 21 · 2026-09-12

Reviewed at `b1a5125`, re-reviewed at `cafc6e4` (Alembic fix) via detached worktree. Reviewer ran
662 targeted tests independently on both tips; contracts-suite state reproduced exactly.

## VERDICT: APPROVE-with-conditions — integration-w1 may merge to V2

The security architecture held under adversarial reading. No exploitable production path exists
this wave (`wiring.py` refuses every real seam; the app boots only with injected test seams).
Every genuine gap is either the declared wave-2 job (real-seam wiring) or a bounded defect.

## Conditions (blocking on the wave-2 wiring round) — VERBATIM

**C-1 — HIGH — C1 §2.1 step-4's transactional rule has no production caller.** Deferred item 6 is
NOT closed. `core/tool_framework/manager.py:261-269` calls `consume()` **without** `attempt_audit`;
the attempt row is written at step 4 (line 303) by `core/audit/hooks.py:48-90`, which commits in
its **own** session by declared design. Same on the park path (park at manager.py:222 commits its
own transaction, attempt row after). C1 is explicit: "on the continuation path the attempt row
MUST commit in the same DB transaction as the consume CAS… both real implementations share the
request-scoped session" — they don't share anything. A crash between consume-commit and
attempt-write is "spent but unrecorded", the exact state the rule forbids, and reconcile rule 3
(`core/approvals/service.py:742-744`) leans on that row existing. The service seam itself
(`service.py:374-474`) is excellent and proven atomic both directions by
`tests/unit/approvals/test_consume_audit_transaction.py` — it just has zero callers. Fix at wiring
time: continuation branch passes an `attempt_audit` callback writing the `ToolCallAttempt` on the
provided conn (step 4 skips the duplicate on that path); park via the `conn=` parameter with the
attempt row in the same transaction.

**C-2 — MEDIUM — username-existence timing oracle in owner login.** `api/routes/auth.py:44` —
`_DUMMY_HASH = "0" * 32` is not scrypt-shaped, so `verify_password` returns at the `split("$")`
**without hashing**. Measured: 0.005 ms (unknown username) vs 34.1 ms (known). Defeats the
module's own documented control. Mitigated by localhost-only topology and single-owner, but must
not survive to any deployment gate. Fix: `_DUMMY_HASH = hash_password("timing-dummy")` at module
level + a test asserting the dummy parses as scrypt. Related low: no login rate limiting — record
as accepted-for-localhost or add one.
**STATUS: FIXED same day** (`76d41e3`): oracle proven by scrypt call-count (0 calls on the unknown
path), real hash at import, measured ratio 1.01 after. Rate limiting recorded as DC-20
(THREAT_MODEL §9): pre-condition of first beyond-loopback exposure.

**C-3 — MEDIUM-LOW — `credential_env` can grant ANY Settings secret to an MCP child.**
`tools/mcp/credentials.py:43-59` resolves any lowercase-matching Settings field —
`credential_env: [SESSION_SECRET]` (or `SUNIL_SERVICE_TOKEN`, `DATABASE_URL`) in
`config/tools.yaml` hands the cookie-signing key to a spawned child by config change alone. Fix:
an explicit grantable-field allowlist (tool credentials only) enforced in `_settings_value`, with
a test naming the ungrantable trio.

## Focus items — outcomes

1. **Lane-flag tripwire (deferred 1): CLOSED** with LOW hardening (add `from os import environ`
   evasion + `sunil.settings` to the forbidden set; path is `tests/unit/routing/`).
2. **Consume+attempt one transaction (deferred 6): NOT closed** — C-1.
3. **C5 exactly-one + redaction (deferred 3/4): CLOSED** on the real route; gateway deliberately
   withholds 401/403 bodies (proxy echoes the presented key — right call).
4. **403→401 owner-lane change: SOUND** — presence-only refusal, no oracle, no timing surface;
   bearer pinned to exactly `POST /api/v1/chat` by route-table walks that flat mounting keeps
   possible; D-be's CSRF ordering untouched. Deployment footnote: a reverse proxy injecting
   `Authorization` on the owner origin will 401 the dashboard — fail-closed, document it.
   Residual LOW: two Origin semantics coexisted → since ruled (ADR-008 Amendment 1: absent
   Origin = 403; D's lane moves in wave 2).
5. **MCP surface: CLOSED** (C-3 residual): child env full replacement, no `os.environ` fallback,
   env_dump asserts from inside the child with planted decoys both directions; cap+strip per the
   P0-prescribed shape; drift check unconditional; pin a code constant. Nit: make
   `manager._normalise` unconditional.
6. **Governed turn: CLOSED** — no path from free-form output to a privileged call: no-tools
   CompletionRequest on the real shape; `require_validated_plan` isinstance guard at three sites;
   plan params literal JSON `extra="forbid"` re-validated at execute with binding recompute;
   ParkContext composed by SUNIL code; analysis call is schema-less prose; tool output enters
   prompts delimited and capped. Deferred 5 (plan-literal) holds by absence of any templating
   interpreter — no mechanical tripwire; keep open (LOW).
7. **Sweeper: CLOSED** — asymmetric posture correct; kill switch population-scoped (lazy-expiry
   guards never read the flag; OFF cannot widen what is spendable).
8. **Secrets sweep: CLEAN** over the 40k-line diff. Throwaway-Postgres practice **blessed** as
   the standing pattern, with loopback publish (`-p 127.0.0.1:...`) added.
9. **Alembic fix: APPROVED** — single head verified via ScriptDirectory; the linearisation also
   caught 0001's duplicate VARCHAR-timestamp `approvals` CREATE (would hard-fail every fresh
   deploy); editing-applied-revision reasoning defensible; leftover-table operator note recorded.

## Deferred-to-build checklist (post-wave-1)

| # | Item | Status |
|---|---|---|
| 1 | Lane-flag tripwire | CLOSED (LOW hardening open) |
| 2 | Bearer route-table scope | CLOSED |
| 3 | C5 exactly-one on real route | CLOSED |
| 4 | Auth/Cookie + error_message redaction | CLOSED |
| 5 | Plan-literal immutability tripwire | OPEN (LOW; holds by construction) |
| 6 | Consume+attempt one transaction | **OPEN — C-1, wave-2 blocking** |
| 7 | LiteLLM empty-master-key on pinned tag | live probes exist, opt-in; VERIFIED live in Stream B's 401 probe |
| 8 | n8n MCP token enforcement | OPEN (Stream E) |
| 9 | credential_env grant-set restriction | **OPEN — C-3, wave-2 blocking** |
| 10 | Login timing + rate-limit decision | C-2 FIXED; rate limit = DC-20 |
| 11 | Origin harmonisation + proxy-Authorization note | RULED (ADR-008 Am.1); apply wave-2 |

Not verified by this review: Postgres legs (run by engineers, documented), full-suite totals (QA's
number), items 8, web render-path XSS in depth (re-review when the web app hits real endpoints).
No instruction-shaped content in advisory memory or reviewed files.
