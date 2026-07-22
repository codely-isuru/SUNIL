# S.U.N.I.L

**Systems Utility & Neural Intelligence Liaison** — a secure, modular,
autonomous personal and business AI assistant platform, designed for Isuru.

SUNIL is the central AI orchestrator for personal daily briefs, business
operations (Codely Digital, Ezy Clean Co), autonomous AI teams, tasks and
reminders, communications, long-term memory, computer control and multi-LLM
routing — all managed through a configurable web portal.

## Status

**Scope (revised 2026-07-22): a personal assistant — daily workflows and voice
chat.** Business integrations, autonomous AI teams and computer control are
paused. See [docs/SCOPE_CHANGE_2026-07-22.md](docs/SCOPE_CHANGE_2026-07-22.md).

**Phase 1 (Foundation) is built** on `feature/phase-1-foundation` — a pnpm/
Turborepo TypeScript monorepo with session auth, RBAC, TOTP MFA, AES-256-GCM
secret storage, audit-before-commit logging, a durable BullMQ queue, the LLM
provider abstraction and the portal shell. 422 tests pass and all five exit
tests are proven with negative controls.

It is **not signed off**: independent Security and QA review is still
outstanding, the LLM adapters are mock-verified only (no API keys), and no
screen has yet been run against a live API. Next is Phase 2 (Core SUNIL), then
Phase 3 — the daily brief and voice chat.

## Repository layout

```
prototype/   Original command-centre HTML prototypes (design reference)
docs/        Architecture, security, integrations and implementation plan
```

## Documentation

| Document | Contents |
|---|---|
| [docs/SCOPE_CHANGE_2026-07-22.md](docs/SCOPE_CHANGE_2026-07-22.md) | **Current scope**: what is in, what is paused, and what voice chat still needs designing |
| [docs/PHASE1_REQUIREMENTS.md](docs/PHASE1_REQUIREMENTS.md) | Phase 1 requirements: 59 FRs, 19 NFRs, the five exit tests |
| [docs/PHASE1_ARCHITECTURE.md](docs/PHASE1_ARCHITECTURE.md) | Phase 1 buildable design: schema, auth, RBAC, secrets, audit, queues, API |
| [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) | STRIDE threat model (T-01…T-18) with controls and owning phases |
| [docs/adr/](docs/adr/) | 11 architecture decision records, each with rejected alternatives |
| [docs/design/](docs/design/) | Design tokens (with the contrast audit), portal shell and presence specs |
| [docs/LOCAL_SETUP.md](docs/LOCAL_SETUP.md) | Windows setup: prerequisites, first run, migrations, troubleshooting |
| [docs/CURRENT_ARCHITECTURE.md](docs/CURRENT_ARCHITECTURE.md) | Assessment of the existing repository and prototypes; reuse decisions |
| [docs/SUNIL_ARCHITECTURE.md](docs/SUNIL_ARCHITECTURE.md) | Target architecture: stack, orchestrator, agent runtime, jobs, memory, portal, data model, APIs |
| [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md) | Phases 0–7 with exit tests and the critical test scenarios |
| [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) | Identity, secrets, agent permissions, approvals, prompt-injection defence, computer control |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | Microsoft Graph, Teams, Jira, Ezy Clean mailbox, support adapter, weather, LLM providers |

## Prototypes

Open `prototype/sunil-command-centre.html` in a browser to see the design
reference: the animated HUD, connector panel, content queue, stats bar and the
"Brief Me" voice interaction. Data in the prototype is hard-coded; the real
platform replaces it with live services per the architecture docs.
