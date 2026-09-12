# integration-w2r1 — merge record (2026-09-12)

Merged lanes: S2-rulings (C4 v1.2.0 + R7), S2-c4-v120 (parcel 1), S2-wiring (real seams, C-1/C-3,
R2/R3, e2e evidence), qa-w2r1 (delta review + fake-wired decision test). Suite at merge:
947/0/4 SQLite x3, 992/0/4 Postgres x2. Verdicts: QA PASS-with-conditions; Security C-1 CLOSED,
C-3 CLOSED, APPROVE (delta re-verification vs THREAT_MODEL §9).

## Open items lifted to integration level (QA condition 3)
1. **§7.5 — parked C5 envelope carries approval_id=""** (real manager returns data=None on
   approval_required; the integration double lied). SA ruling in flight (R8); blocks any
   "end-to-end works on real wiring" claim, not this merge. Security prefers option (b): read the
   ref from the audited attempt row.
2. **R7.2 — reconciliation rule 4** (refused/expired + unfinalised task -> finalise; plus the
   lazy-expiry finalisation gap) — owed in-wave; SA delta in flight.
3. **dev-up DATABASE_URL template-password warning** + localhost ::1 stall — scripts lane, small.
4. **Live-model turn awaits owner provider keys** (infra/.env.litellm, SECRETS_SETUP.md).

## Review residuals for the next hardening pass (all LOW/INFO, security delta)
R-1a factory silent-downgrade combination (fix: guard on engine only, ctor raises, named test) —
the one Security wants next · R-1b hoist the hasattr out of the per-plan closure · R-1c
_pending_events growth on caller-rollback · R-3a base_url_env grantable-URL allowlist symmetry ·
R-6a `from sunil import settings` ImportFrom-alias dodge in the tripwire · D-1 S2-wiring.md §1
overstates lifespan-start failure handling (doc fix or align) · QA F2 tripwire claim said 3 red,
reproduces 2.
