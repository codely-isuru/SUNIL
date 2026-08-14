# ADR-006 — Secrets: environment / `.env` loaded as `SecretStr`, plus a value-registry redaction mechanism

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §26 rules 1/5/6, `docs/ARCHITECTURE_V1.md` §9.1/§8.3,
FR-005, NFR-001/005, **ET-10**, `docs/ENVIRONMENT.md` §8.

## Context

Three secrets exist in M1: `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, `SESSION_SECRET` (plus
`OWNER_PASSWORD`, used once by the seed script). None are present in the environment today; the owner
supplies them after Gate 2.

FR-005 forbids secrets in source control. ET-10 goes further: *no secret value may appear in any
prompt sent to the LLM or in any persisted log for the request.* That is a claim about runtime
behaviour, and no policy statement can satisfy it.

## Decision

**Storage:** `pydantic-settings` `BaseSettings`, every secret typed `SecretStr`, loaded from process
environment or a gitignored `.env`. `.env.example` is committed with **placeholder values only** and
is the single inventory of what must be set (`ARCHITECTURE_V1.md` §14.4).

**Handling:** secrets are injected into clients **at construction** — `AsyncAnthropic(api_key=…)`,
an `httpx` `Authorization` header — and never string-formatted into a prompt, plan, tool parameter,
log message or error.

**Redaction as a mechanism, not a promise** — two parts:

1. **A value registry.** `settings.py` calls `redaction.register(value)` once at startup for every
   loaded secret, including the password inside a Postgres `DATABASE_URL`.
2. **`redaction.scrub()`**, run as a structlog processor on every log line *and* on
   `llm_calls.request_*` / `llm_calls.response_*` / `tool_calls.parameters` / `tool_calls.result` /
   `audit_events.detail` **before insert**. It replaces (a) any registered secret value anywhere in a
   string, (b) the value of any key matching `api_key|apikey|authorization|token|secret|password|
   cookie`, (c) high-signal patterns `sk-ant-…`, `gh[pousr]_…`, `Bearer …`.

ET-10 is then two tests: a registered secret never appears in log output; a registered secret never
appears in a persisted `llm_calls` row.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **AWS Secrets Manager / SSM Parameter Store** | The correct answer for a deployed system, and where V1 goes when it is hosted. Rejected for M1: there is no AWS account provisioned for SUNIL, it adds an IAM dependency and network calls to local startup, and SRS Assumption A5 says a local run is sufficient for M1 sign-off. |
| **OS keyring (`keyring` package)** | Ties secrets to an interactive desktop session, breaks in containers and CI, and adds a native dependency on Windows for a single-user local build. |
| **SOPS / age-encrypted secrets in the repo** | Good for team secret distribution; here it adds a binary tool and a key-management problem to protect three values one person owns. |
| **HashiCorp Vault** | Correct at scale, absurd at this scale. |
| **Plain `os.environ[...]` with no typing** | Works, but loses `SecretStr`'s accidental-`repr()` protection and gives no single place to register values for redaction — which is what makes ET-10 testable. |
| **Redaction by prompt discipline only ("never put secrets in prompts")** | This is already the primary control. But a control with no mechanism behind it is a claim, and this document's standing rule is that no document claims a control the code does not have. |

## Consequences

- `redaction.scrub()` is on the write path for every log line and several DB columns. It is a pure
  string/dict walk over small payloads; measure it if p95 ever tightens.
- Redaction is a **second** line of defence. The first is that secrets are never assembled into
  prompt text at all. If scrubbing is ever seen actually redacting something in `llm_calls`, that is
  a defect to fix upstream, not a control working as intended.
- Migrating to a real secret manager later changes only `settings.py`; nothing else reads a secret.
- **Debt:** the SQLite file and `.env` sit unencrypted on disk (D-7). `var/` and `.env` are
  gitignored; disk encryption is the owner's machine-level concern.
