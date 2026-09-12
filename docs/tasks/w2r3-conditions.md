# w2r3 conditions ledger (wave-2 final reviews, 2026-09-12)

Transcribed by the DM from the QA and Security final verdicts (mirrored in
docs/reviews/2026-09-12-w2-*); SA signs off at w2r3 step 0. Every item has an owner.

## Blocking conditions on named triggers
- **C-A (Security, MEDIUM)** — blocks the wave that lands ANY production memory-write/seeding
  path: (1) recalled memory enters the analysis prompt as role="system", uncapped
  (agent.py:202-205) — must become delimited untrusted framing + non-system role + byte cap;
  (2) C3 §2's local_only prompt filter is implemented nowhere — a recalled local_only memory
  would ship to a remote model; (3) memory-write authorization is currently answered by absence —
  the write wave answers it explicitly (who writes, which ADR-014 class, permission row or not).
  Owner: the memory-write wave.
- **QA F-1 (MEDIUM)** — R16's replacement module dropped the catalogue-wide fix_and_pr scan with
  no successor; the surviving pin is vacuously true against a dormant tool. Re-land the
  whole-catalogue scan as a standalone module in the w2r3 parcel. Owner: SA (delta) +
  backend (apply).
- **QA F-2 (MEDIUM, pre-existing on V2)** — the PRODUCTION park exit's ApprovalRef
  (manager.py:527) is covered by nothing (approval_ref=None survives both legs green). Add the
  test in w2r3. Owner: backend (chokepoint lane).

## Next docs/hardening pass (C-B + LOW/INFO)
- Security F-3: THREAT_MODEL DC-21 control #3 wording — a lifespan-start 403 leaves the tool
  present-but-transport_error, not absent (fail-closed either way). One line. Owner: SA.
- Security F-4/F-5: retention DC row for memories (no reaper) + entity tables (business PII
  outside ADR-014 scope) — registered as DC-22 with this merge. Owner: sweep milestone.
- Security F-6: n8n-setup.sh passes secrets via argv (process-table visible) — accepted-for-dev,
  fix before any shared host. F-7: seq-collision liveness nit. F-8: entity-linked recall crosses
  user_id — re-open at multi-user. QA F-3: ADR prose stragglers (/mcp path in ADR-032/033
  bodies). QA F-4: KeyError-shaped tripwire message. QA F-5: line-number cite. Owners: SA docs
  pass / QA.

## Carried w2r3 parcel (from R13/R15/R16)
EntityResolver wiring · memories reaper · github capture-gated re-landing (ADR-034 Amendment 1,
composed merge, transcription pin, F-1 scan re-land) · engine-enablement ADR (push authority +
runtime isolation, one decision) · embed() C2 v2.0.0 candidate (Stream B keyed round) ·
assert_never turn.py guard · live-model turn + GatewayEmbedder round-trip on owner keys.
