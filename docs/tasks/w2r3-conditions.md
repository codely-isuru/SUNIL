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
- ~~Security F-3~~ — **DONE 2026-09-17** (SA, `task/S3-docs` @f1911e8): THREAT_MODEL DC-21
  control #3 now states what the code does — lifespan-start 403 → present-but-`transport_error`
  (fail-closed at the chokepoint, `main.py` lifespan); wiring-time failure → absent. DC-21a
  register row deleted; the dated note at the corrected text records the closure.
- Security F-4/F-5: retention DC row for memories (no reaper) + entity tables (business PII
  outside ADR-014 scope) — registered as DC-22 with this merge. Owner: sweep milestone; trigger:
  the sweep/housekeeping milestone, and any write-path wave inherits C-A first.
- Security F-6: n8n-setup.sh passes secrets via argv (process-table visible) — accepted-for-dev.
  Owner: integration (platform lane); trigger: before any shared or multi-user host.
- Security F-7: seq-collision liveness nit. Owner: backend; trigger: next hardening pass.
- Security F-8: entity-linked recall crosses user_id. Owner: the multi-user wave; trigger:
  re-opens the moment a second user exists.
- ~~QA F-3~~ — **DONE 2026-09-17** (SA, `task/S3-docs` @cc6f329): both `/mcp` prose stragglers —
  ADR-033's Decision-body default and ADR-032 Amendment 1's forward-looking consequences sentence
  — corrected/annotated in place, dated, per the ADR-032 convention.
- QA F-4: KeyError-shaped tripwire message. Owner: backend (QA verifies the message names the
  tripwire, not the dict access); trigger: next hardening pass.
- ~~QA F-5~~ — **DONE 2026-09-17** (SA, `task/S3-docs` @6df8c59): ADR-033 cites `.env.example`
  by key (`SUNIL_N8N_MCP_BASE_URL`), not line number — the cited `:193` had already rotted
  to `:198`.

## Carried w2r3 parcel (from R13/R15/R16)
EntityResolver wiring · memories reaper · github capture-gated re-landing (**ADR-034 Amendment 1
LANDED 2026-09-17** — SA, `task/S3-docs` @59b3ac2: bindings, composition, naming law ready for
the re-landing lane; still in flight there: composed-merge executor, transcription pin, F-1 scan
re-land) · engine-enablement ADR (push authority + runtime isolation, one decision) · embed() C2
v2.0.0 candidate (Stream B keyed round) · assert_never turn.py guard · live-model turn +
GatewayEmbedder round-trip on owner keys.


## Post-round ledger update (DM, 2026-09-18, from the QA-R3 delta review)
CLOSED this round (verified stronger than claimed): QA F-1 (standalone scan, bites), QA F-2
(both mutants' tests, manager.py byte-identical), R13 EntityResolver, memories reaper, DC-23
comment, SA docs items. C-A correctly untriggered (no production memory-write caller exists).

STILL OPEN — SA pen, next docs touch:
- QA-R3-1: annotate ADR-034 Am.1's example verb (illustrated update_issue; capture proved
  issue_write) — pinned in code 5 places, needs the dated ADR annotation.
- QA-R3-3: ARCH §5 row for SUNIL_MEMORY_REAPER_ENABLED (§5 claims completeness and misses it);
  consider a §5↔Settings parity test so this class can't recur.

ENVIRONMENTAL (owner actions, then one evidence round):
1. Docker Desktop 4.91 repair-install (corrupted iso, digest-proven; do NOT factory-reset —
   54GB data vhdx). Unblocks: Postgres legs (10 gated tests), live github read, live-proof
   legs 2/3, security deferred item 7.
2. Replace ANTHROPIC_API_KEY (401 direct from Anthropic) in infra/.env.litellm.
3. Replace GITHUB_TOKEN with a fine-grained read-only single-repo PAT (old one dead AND
   fragment-disclosed in a transcript — rotation mandatory; incident + lesson on record).
