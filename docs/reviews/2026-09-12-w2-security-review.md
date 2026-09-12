# Security Review — Wave 2 (rounds 1+2) · Minions Team 21 · 2026-09-12

Round 1 (@5e0de87): **C-1 CLOSED** (consume+attempt genuinely one transaction on both paths;
rollback semantics correct — a failed audit write rolls back the consume; crash tests
regression-catching by construction; seam decided at boot), **C-3 CLOSED** (allowlist checked
before the Settings lookup on every resolution path; growth-pinned by an equality test).
APPROVE. Residuals R-1a/R-1b/R-1c/R-3a/R-6a/D-1 — all closed in the S2-close round.

Round 2 (@265fae8): **APPROVE-with-conditions.** The wave's live posture:

- **The plan call structurally never sees memory** — exactly three fixed sources; recalled
  content reaches only the schema-less analysis call.
- **Memory has ZERO production writers**, and an un-audited future write raises (fail-closed);
  §4a's privacy arithmetic is real in code (upgrade-only merge, laxer-append rejected,
  advisory-locked, CHECK-bounded labels the provider cannot reclassify); scope is structural SQL
  with typed bindparams — zero string interpolation.
- **n8n**: exports carry credentials as placeholder references never values; the MCP trigger is
  pinned bearerAuth by a red-verified test; DC-21's compensating controls all present; W1
  deferred item 8 (bearer enforcement) CLOSED with recorded live evidence; setup scripts generate
  secrets properly and never print them.
- **OpenHands seam containment holds on the merged tree** (closed verb set before permission,
  branch validation incl. the sunil/main case, no-prose-to-prompt, project_key-only TaskSpec,
  no LLM call in the agent).
- **The dormancy is inert**: comment blocks only, no executable path to the deprecated server,
  GITHUB_TOKEN reads confined to the native read-only tool.
- **ZERO unattended writes in the live permission matrix — machine-enforced**: the whole-matrix
  tripwire computes every allow × read_only:false and asserts the empty set; the only allow
  anywhere is the read-only native github read.
- Secrets sweep over the full wave diff: clean.

**Conditions:** C-A (memory-write gate — system-role recall framing, unimplemented local_only
filter, unanswered write authorization) registered as **DC-23**, blocking whichever wave lands a
memory write/seed path. C-B: DC-21 wording fix (**DC-21a**) and the retention row (**DC-22**).
Non-blocking F-6/F-7/F-8: see docs/tasks/w2r3-conditions.md.

**Unverifiable offline:** the live n8n 403/200 matrix (recorded fixture + export pins verified
instead), GatewayEmbedder round-trip (mock transport, module says so), OpenHands vendor mapping
(honestly labelled unverified-until-first-live-boot), the Postgres parity leg (engineer-run;
reviewer ran the SQLite leg + every security pin).
