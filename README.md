# S.U.N.I.L

**Systems Utility & Neural Intelligence Liaison** — a secure, modular,
autonomous personal and business AI assistant platform, designed for Isuru.

SUNIL is the central AI orchestrator for personal daily briefs, business
operations (Codely Digital, Ezy Clean Co), autonomous AI teams, tasks and
reminders, communications, long-term memory, computer control and multi-LLM
routing — all managed through a configurable web portal.

## Status

**Phase 0 — assessment and design.** The repository currently contains the
original UI prototypes and the full architecture/design documentation.
Implementation begins with Phase 1 (Foundation).

## Repository layout

```
prototype/   Original command-centre HTML prototypes (design reference)
docs/        Architecture, security, integrations and implementation plan
```

## Documentation

| Document | Contents |
|---|---|
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
