# SUNIL — Security Model

SUNIL reads private email, controls computers and spends money on LLM APIs.
Security is therefore an architectural property, not a feature. This document
defines the model every phase must comply with.

## 1. Identity and access

* **Single-owner system**: Isuru is the owner; additional users are invited
  only. Public registration is disabled.
* Session-based auth with short-lived, httpOnly, `SameSite=Lax`, Secure
  cookies; server-side session revocation; secure refresh handling.
* Optional TOTP MFA on the owner account.
* RBAC: roles → permissions → route guards. Every API route declares its
  required permission; default deny.
* Rate limiting and brute-force lockout on auth endpoints; CSRF tokens on
  state-changing browser requests; strict Content-Security-Policy; output
  encoding everywhere (no `innerHTML` with untrusted data — a direct lesson
  from the prototype).

## 2. Secrets

* All credentials (OAuth tokens, API keys, SMTP passwords) live in the
  `SecretStore`: AES-256-GCM envelope encryption with a master key from the
  environment, behind an interface swappable for AWS Secrets Manager, Azure
  Key Vault or HashiCorp Vault.
* APIs never return a stored secret. The portal shows identity, scopes and a
  masked fingerprint only; keys are write-only after save.
* Credential rotation supported per integration account.
* The logger redacts known secret patterns and named fields globally; LLM call
  logs are redacted before persistence. Never logged: passwords, API keys,
  OAuth tokens, full sensitive email bodies.
* No credentials in Git. `.env.example` carries names and comments only.

## 3. Agent permission model

Agents are configuration; their authority is enforced by the runtime, not by
prompt text:

* **Tool allowlist** per agent — an agent without `email:send` cannot invoke
  the send tool at all; the tool is absent from its schema.
* **Integration permissions** per agent per account (read / categorise /
  summarise / create task / draft / send / forward / archive / label / delete
  as separate grants — see §6).
* **Budgets**: max tokens/cost per task and per month; the loop halts and
  reports `task_blocked` when exceeded.
* **Timeouts** and heartbeats; a silent agent is marked failed and its job
  retried or escalated.
* **Memory access levels** per agent; sensitive-classified memories are
  excluded from agents without clearance.

## 4. Approval gates

Actions that always require explicit approval unless a narrowly scoped trusted
rule exists: sending external email/replies, forwarding information, Jira
mutations, computer actions above the safe tier, running non-allowlisted
commands, modifying/deleting files, deployments, spend above budget threshold,
sharing confidential information, any financial action, permanent deletion of
anything.

Each approval request records: requesting agent, intended action, reason,
target, exact data to be sent/changed, risk level, related task. Decisions:
approve / reject / edit-and-approve / approve-once / create trusted rule.
Approvals and decisions are audit-logged; a workflow parked on approval resumes
only on an affirmative decision.

## 5. Prompt-injection defence

External content (emails, web pages, documents, tickets, Teams messages) is
**untrusted data, never instructions**:

* External text is wrapped in delimited data blocks in prompts, with an
  explicit contract that its contents cannot change task, permissions or
  tools.
* Permissions are enforced *outside* the model (runtime allowlists, approval
  gates), so even a fully successful injection cannot execute anything the
  agent was not already allowed to do silently.
* No agent may grant itself or another agent additional permissions; grants
  come only from the portal by an authenticated human.
* Classifier + heuristic screening flags injection-looking content for review.
* Dedicated prompt-injection test suite (brief §17.11) runs in CI.

## 6. Email action permissions

Separate, per-account grants: read, categorise, summarise, create task, create
reminder, draft reply, send reply, forward, archive, label, delete.

Defaults: read/classify/summarise/suggest/draft are automatable; external
send, forward, permanent deletion and sensitive account changes require
approval. Account-specific trusted rules can later enable controlled
auto-replies (e.g. Ezy Clean booking confirmations) with tight scope, and every
automated email action is logged with the message's external ID.

Filtered marketing/SEO mail goes to a reviewable blocked category; SUNIL never
permanently deletes mail automatically.

## 7. Computer control

* The executor service binds to localhost/private network only and is never
  exposed publicly or via the compose ingress.
* Permission tiers: (1) read-only, (2) create files, (3) edit files, (4) safe
  allowlisted commands, (5) browser interaction, (6) application control,
  (7) system configuration, (8) destructive/high-risk. Tiers 7–8 always
  require approval; deletion, credentials, financial transactions, external
  messages, production deploys and system config are approval-gated
  regardless of tier.
* Command allowlists *and* denylists; working-directory jail per agent;
  sandboxed execution where possible; execution timeout and resource limits;
  full output capture; screenshot/evidence capture for UI actions; rollback
  (git snapshots / file backups) where possible; confirmation for destructive
  actions; secret redaction in captured output.
* Every action writes an audit record before and after execution.

## 8. Platform hardening

* Zod validation on all external input; parameterised queries via Prisma (no
  raw SQL without review); SSRF protection on any user/agent-supplied URL
  fetch (deny private ranges, resolve-then-connect checks); file-upload
  validation (type, size, content sniffing) with a malware-scanning extension
  point; idempotency keys on mutating endpoints.
* Environment-specific configuration; production config never defaults to
  permissive values.

## 9. Audit and observability

Append-only audit log for: auth events, permission changes, integration
connect/disconnect, every outbound action (email, Jira, Teams, computer),
approval decisions, secret access, memory edits/deletions, workflow and agent
lifecycle events. Audit records carry actor (human or agent), action, target,
before/after where applicable, and timestamps. Failure notifications surface
in the portal and via configured channels.

## 10. Development rules (security subset)

No production actions during development; no real emails sent in development;
no real customer data in tests; external providers mocked in CI; the
computer-control service never publicly exposed; no unrestricted tool access
for any agent; explicit approval for destructive, financial, production or
externally visible actions — always.
