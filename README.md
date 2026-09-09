# S.U.N.I.L

**Systems Utility & Neural Intelligence Liaison** — a secure, modular,
autonomous personal and business AI assistant platform, designed for Isuru.

SUNIL is the central AI orchestrator for personal daily briefs, business
operations (Codely Digital, Ezy Clean Co), autonomous AI teams, tasks and
reminders, communications, long-term memory, computer control and multi-LLM
routing — all managed through a configurable web portal.

## Branches

| Branch | What it holds |
|---|---|
| `main` | **V1 / M1 — live-verified build** (FastAPI + Next.js, 564 tests): orchestrator, validated plans, permission engine, GitHub tool, audit spine. Kept as the reference implementation and fallback. |
| `V2` | **The V2 rebuild (this branch)** — clean slate by owner decision 2026-09-10. Docs only until the Minions team delivers Phase 0. |

## Status (V2 branch)

**Phase 0 — contracts & platform.** Read [`docs/STATUS.md`](docs/STATUS.md) first.
The finalised architecture is [ADR-030](docs/decisions/ADR-030-integrate-open-source-components.md)
(n8n edition) + Amendment 1 (clean-slate rebuild); the build plan is
[`docs/V2_DEVELOPMENT_PLAN.md`](docs/V2_DEVELOPMENT_PLAN.md); the diagram is
[`docs/design/ARCHITECTURE_V2_FINAL.html`](docs/design/ARCHITECTURE_V2_FINAL.html).
