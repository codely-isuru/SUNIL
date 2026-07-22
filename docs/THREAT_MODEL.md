# SUNIL — Phase 1 Threat Model

_Document owner: Solution Architect / Technical Lead (Minions delivery team)_
_Method: STRIDE per trust boundary/entry point · Scope: Phase 1 (Foundation) surface only_
_Companions: `PHASE1_ARCHITECTURE.md` (control locations), `SECURITY_MODEL.md` (binding
model), `docs/adr/*` (decision records)._

> Phase 1 is a local-only, single-owner foundation with no external integrations, no
> outbound actions and no production deployment. Several classic threats therefore have no
> Phase 1 attack surface — they are still listed, marked **Deferred**, with the owning phase
> named, because the foundation must not make them harder to mitigate later.

Likelihood/impact scale: L/M/H, judged for the Phase 1 deployment context (developer-operated
local stack, real secrets possible in `.env`, no public exposure).

---

## 1. Assets

| ID | Asset | Why it matters |
|---|---|---|
| A-1 | Owner credentials (password hash, TOTP secret, recovery codes) | Total control of the platform |
| A-2 | Session tokens (cookie values; hashes in DB) | Equivalent to credentials while valid |
| A-3 | Master encryption key (`SUNIL_MASTER_KEY` in `.env`) | Unwraps every stored secret |
| A-4 | Stored secrets (`secrets` table — future LLM keys, MFA seeds) | Direct financial/access abuse |
| A-5 | Audit log integrity | The evidence layer every later phase relies on |
| A-6 | RBAC data (roles/permissions/user_roles) | Tampering = privilege escalation |
| A-7 | Queue state (Redis) + job history (Postgres) | Silent loss breaks durability guarantees (ET-4) |
| A-8 | The dependency supply chain / lockfile | Compromise = arbitrary code in every service |

## 2. Trust boundaries and entry points

```
[Browser] --(TB-1: HTTP + session cookie + CSRF header)--> [apps/web (Next)] --(same-origin fetch)--> [apps/api]
[apps/api] --(TB-2: compose network)--> [Postgres]        (app role; no superuser)
[apps/api|worker|scheduler] --(TB-3: compose network)--> [Redis]  (no auth in dev profile — see T-14)
[apps/worker] --(TB-4: outbound HTTPS — Phase 1: mock transports only)--> [LLM providers]
[Operator host] --(TB-5: .env file, docker socket, volumes)--> [entire stack]
```

Entry points: `POST /api/auth/login`, `POST /api/auth/mfa/verify`,
`POST /api/invitations/:token/accept`, `GET /api/system-health` (the public four); every
authenticated route; the invitation link conveyed manually by the owner (Gate 1); Compose
config and `.env` on the host; the package registry at install time.

---

## 3. Threat catalogue

Status key: **Mitigated (P1)** = control ships and is exit-tested in Phase 1 ·
**Partial (P1)** = Phase 1 controls exist, residual named · **Deferred (Pn)** = no Phase 1
surface or control lands in phase n, owner named.

### T-01 — Session theft (S: Spoofing)

Cookie stolen via malware, log leak, DB read, or network interception.
**Likelihood M · Impact H.**
Controls: `HttpOnly` (no script read) + `Secure`/`__Host-` prefix in secure profile +
`SameSite=Lax` (§6.1); DB stores only SHA-256 hashes — a DB dump yields no usable tokens;
idle 8 h / absolute 24 h caps the window; immediate server-side revocation (per-request row
validation, no session cache); bulk revoke per user (ET-1 1.11); tokens never logged
(redaction §9.5). Residual: theft of the live cookie from the owner's own browser/host is
out of scope for the platform (host security). **Mitigated (P1)** — ET-1.

### T-02 — Session fixation / MFA-stage abuse (S)

Attacker fixes a known session id, or a `PENDING_MFA` session is used as if authenticated.
**L · H.**
Controls: session tokens are only ever server-generated at login (no client-supplied id is
ever accepted or persisted); the token is **rotated on MFA elevation** (§6.2), so a
pre-auth token never becomes a privileged one; `PENDING_MFA` sessions are accepted by exactly
one route (`/api/auth/mfa/verify`) — the global guard rejects them elsewhere. **Mitigated
(P1)** — ET-1 1.5.

### T-03 — Credential brute force / stuffing (S)

**H (attempt) / L (success) · H.**
Controls: argon2id via `@node-rs/argon2` (ADR-003); 5-failure/15-min lockout with 15-min
cool-off (Gate 1 thresholds, env-tunable); 20 req/min per-IP limit on auth endpoints;
generic failure responses + dummy-hash timing equalisation (no account-existence oracle,
§6.3); TOTP as a second factor; all failures + lockouts audited. Residual: lockout counters
live in Redis — a hard crash inside the 1 s AOF window (ADR-002) can reset an in-progress
window once; accepted and documented. **Mitigated (P1)** — ET-1 1.3/1.4.

### T-04 — CSRF (S/T)

Cross-site request rides the session cookie into a mutating endpoint. **M · H.**
Controls: per-session synchronizer token in the `X-CSRF-Token` header, constant-time
compared, never carried in a cookie (ADR-009, §6.5); `SameSite=Lax` as the ambient layer;
strictly same-origin browser topology — the portal proxies `/api/*` so no cross-origin
request path exists (ADR-011); violations 403 + audited. `Origin`-header validation is
**deferred** to the Phase 2 ingress ADR (Amendment A2) — the token is the FR-028 control.
**Mitigated (P1)** — ET-1 1.9.

### T-05 — Privilege escalation via RBAC gaps (E: Elevation)

A route ships without a permission declaration; a permission check is skipped; a viewer
reaches admin surface; a second owner is minted. **M · H.**
Controls: **default deny is structural** — undeclared routes are rejected at runtime by the
global guard *and* fail the route-enumeration test naming the offender (§7.4); permissions
resolved per request (no stale grants — Gate 1); privilege reduction revokes sessions
atomically with the role change at the single `RoleAssignmentService` choke point (§6.6);
`role:assign` is owner-only; single-owner enforced down to a partial unique index (ADR-001);
UI hiding is never the control (ET-2 2.6). **Mitigated (P1)** — ET-2.

### T-06 — Secret exfiltration via API or logs (I: Information disclosure)

A stored secret value leaves through a response body, error page, OpenAPI example, usage
record, or log line. **M · H.**
Controls: `SecretValue` wrapper (serialises to `[REDACTED]`; plaintext only via `.use(fn)`);
DTO-allowlisted secret endpoints + interceptor that throws on a `SecretValue` in any
response; dependency-cruiser fence on `SecretStore.get` call sites; global Pino redaction
(named fields + patterns) applied to logs *and* audit payloads *and* usage-record errors
(§8.4, §9.5); write-only secret fields in the portal; ET-5 sentinel scans across responses,
headers, logs, usage records and the portal bundle as the standing regression. **Mitigated
(P1)** — ET-5; the requirements flag this scan as re-run in every later phase.

### T-07 — XSS in the portal (T/I)

The prototype's `innerHTML` habit imported into the product; stored script in a user-editable
field executes. **M · H (leads to T-01/T-04 token theft).**
Controls: framework-escaped rendering only; `react/no-danger` lint = error; CSP
`script-src 'self' 'nonce-…'`, `object-src 'none'`, `frame-ancestors 'none'` (§6.7);
FR-031's literal `<script>` round-trip test; CSRF token held in memory (not readable
cross-origin, though XSS itself would sit inside the origin — hence CSP as the primary
control). **Mitigated (P1)** — FR-031 tests.

### T-08 — Audit tampering or bypass (T/R: Tampering, Repudiation)

A mutation commits without a record; a record is edited/deleted; timestamps forged. **M · H.**
Controls: audit-before-commit in the same transaction — an unaudited mutation cannot commit
(Gate 1, ADR-005); append-only enforced twice (Prisma client extension + DB trigger);
server-generated timestamps with no caller override; coverage enforced at build time
(decorator enumeration, negative control) and runtime (correlation-id tally); denial paths
audited; audit reads permission-guarded and redacted. Residual: an attacker with the
database superuser role can drop the trigger — DB credential hygiene is the control
(app connects as a non-superuser role; superuser stays operator-only), and tamper-*evident*
storage (hash chaining / WORM export) is **Deferred (Phase 7)**. **Mitigated (P1)** with the
named residual — ET-3.

### T-09 — Queue poisoning / job forgery (T/E)

Crafted job payloads execute unintended work; repeatable definitions duplicated or altered;
Redis used to inject work. **M · M (Phase 1: agents have no tools, so blast radius is low).**
Controls: every job payload Zod-validated at the worker boundary before processing
(NFR-003); only `api`/`scheduler` enqueue, inside the compose network; Job Scheduler ids are
code-defined constants with boot-time reconciliation removing unknown ids (ADR-010);
`noeviction` prevents silent state destruction (ADR-002); agent configs re-validated at load
(empty tool allowlist is schema-enforced — a poisoned job still cannot reach a tool, FR-070);
execution history in Postgres makes anomalies visible. Residual: anyone who can reach Redis
can write keys — see T-14. **Partial (P1)**: payload validation + no-tool blast-radius now;
full job-provenance signing is not planned (accepted); tool-bearing agents are **Phase 2+**
where the orchestrator permission layer takes over.

### T-10 — SSRF (S/I) — anticipated, not yet reachable

User/agent-supplied URLs fetched server-side (integrations, webhooks, Ollama base URL).
**Phase 1 surface:** the only user-configurable outbound URL is `LlmProvider.baseUrl`
(Ollama), and Phase 1 never dereferences it outside mock transports; `provider:write` is
owner/admin-only. **Deferred (Phase 3 — integrations; Phase 6 — browser/computer control)**,
where SECURITY_MODEL §8's controls land (deny private ranges, resolve-then-connect checks).
Phase 1 obligation honoured: the transport seam (ADR-008) gives one choke point where the
SSRF guard will wrap all outbound fetches — recorded so Phase 3 does not scatter fetch calls.

### T-11 — Invitation-flow abuse (S/E)

Token guessed, replayed, or a lesser admin escalates via invitation. **L · H.**
Controls: 32-byte random tokens, stored hashed, 72 h expiry, single-use consumed atomically
in a transaction; mutated/expired/replayed tokens generically refused + audited (ET-1 1.8);
invitations can never carry the `owner` role (service + seed + ADR-001 index); creation
requires `user:invite` and is audited; delivery is owner-conveyed manually (Gate 1) — no
mail transport to intercept. **Mitigated (P1)** — ET-1 1.7/1.8.

### T-12 — TOTP/MFA weaknesses (S)

Seed leakage, code replay, recovery-code reuse. **L · H.**
Controls: TOTP seed stored only via `SecretStore` (envelope-encrypted, never a plaintext
column); one-time enrolment disclosure; accepted-timestep tracking rejects replayed codes;
recovery codes hashed, single-use in a transaction; disable requires password re-auth; all
transitions audited (§6.4). **Mitigated (P1)** — ET-1 1.5/1.6.

### T-13 — Denial of service against the local stack (D)

Request floods; oversized payloads; queue flooding. **L (local-only) · M.**
Controls: per-session (100/min) and per-IP auth (20/min) limits with 429 + `Retry-After`;
Fastify body-size limits; Zod rejects oversized/deep structures at the boundary; Redis
`noeviction` + AOF keeps queue state sane under pressure; health endpoints keep degradation
visible (NFR-010). **Partial (P1)** — real DoS resilience is a production concern,
**Deferred (Phase 7)** with ingress/WAF.

### T-14 — Direct datastore access on the compose network (S/T/I)

Anything reaching Postgres/Redis ports bypasses the API's guards. **L (local) · H.**
Controls: neither service publishes host ports by default (debug profile only, documented);
compose network isolation; Postgres app role is non-superuser (cannot drop the audit
trigger); secrets in Postgres are ciphertext (A-3 never stored); session tokens hashed.
Residual: dev-profile Redis runs unauthenticated — acceptable local-only; `requirepass` +
TLS are **Deferred (Phase 7)** production hardening, flagged in `.env.example` comments now.
**Partial (P1).**

### T-15 — Master-key / `.env` compromise on the operator host (I)

`.env` copied, committed, or logged; key regenerated and data lost. **M · H.**
Controls: `.env` git-ignored with `.env.example` names-only (FR-004); secret-scan step over
working tree and commit range (NFR-005); boot-time key validation (length/absence — no
silent fallback, FR-041); startup error messages never print secret values; LOCAL_SETUP
documents generation + loss consequences (R-07). Residual: an attacker with host-level read
of `.env` defeats local envelope encryption by design — the acknowledged Phase 1 boundary;
managed KMS/Vault is the **Deferred (Phase 7)** upgrade the `SecretStore` interface was
shaped for. **Partial (P1), residual accepted and documented.**

### T-16 — Supply-chain compromise of the dependency set (T/E)

Malicious postinstall script, typosquat, or compromised transitive dep across the ~9
workspace packages. **M · H.**
Controls: pnpm lockfile committed and authoritative; **lifecycle scripts blocked by default**
with an explicit `allowBuilds` allowlist (pnpm 11 name; formerly `onlyBuiltDependencies`) of
`prisma`, `@prisma/engines`, `esbuild` — a new build script is a visible, reviewable event
(ADR-007); pnpm 11's release-age gate, where **every `minimumReleaseAgeExclude` entry
requires Security Reviewer sign-off** (current entries: `@anthropic-ai/sdk@0.112.4` and the
`typescript-eslint@8.65.0` family — open review item); exact-version pins for the
security-core set (§4); no node-gyp toolchain dependencies by design; `pnpm audit` in the
root task set; the small, enumerated dependency budget is itself the control (every addition
is reviewed); mock transports keep CI keyless so a compromised dep finds no provider
credentials in the test environment. Residual: a compromised *runtime* dependency still
executes with service privileges — SBOM/provenance verification is **Deferred (Phase 7)**.
**Partial (P1).**

### T-17 — Repudiation by non-human actors (R)

Agent activity unattributable; system actions invisible. **L · M.**
Controls: `ActorType` includes `AGENT`/`SYSTEM` with id + durable label; agent envelopes
persisted append-only with global sequence; bootstrap writes SYSTEM-actor records; ET-3 3.7
proves agent-actor records round-trip. **Mitigated (P1).**

### T-18 — Prompt injection (S/E) — no Phase 1 surface

No external content enters any prompt in Phase 1 (mock transports; no integrations; empty
tool allowlists). The structural pre-condition Phase 1 does deliver: budgets/timeouts/tools
enforced **in the loop, never in prompt text** (§11.4), so a future injection cannot talk
its way past enforcement that is not in the conversation. Classifier, delimited data blocks
and the CI injection suite are **Deferred (Phase 2 orchestrator onward; hardening Phase 6)**
per SECURITY_MODEL §5.

---

## 4. Phase 1 mitigation summary

| Status | Threats |
|---|---|
| Mitigated in Phase 1 (exit-tested) | T-01, T-02, T-03, T-04, T-05, T-06, T-07, T-08*, T-11, T-12, T-17 |
| Partial — residual named and accepted | T-09, T-13, T-14, T-15, T-16 |
| Deferred — no Phase 1 surface, owner named | T-10 (Phase 3/6), T-18 (Phase 2/6); production hardening residuals of T-08/T-13/T-14/T-15/T-16 (Phase 7) |

\* T-08 residual (DB-superuser tampering; tamper-evident storage) deferred to Phase 7.

## 5. Standing obligations this model creates

1. ET-5's sentinel/response/log scans and ET-2/ET-3's enumeration tests are **standing
   regression suites** — every later phase's new endpoints re-open T-05/T-06/T-08.
2. All outbound HTTP added in Phase 3+ must route through the ADR-008 transport seam so the
   T-10 SSRF guard has one place to live.
3. Any new dependency requiring a build script, or any node-gyp dependency, is a
   threat-model event (T-16), not a routine install.
4. The security reviewer (BL-901) verifies control *presence and location* against this
   document, not against intentions.
