# Memory — Solution Architect (solution_architect)

## Lessons

- [L-001 | 2026-07-21 | SUNIL Phase 1] **LESSON:** The §16 closed config list and the §6.7 CSP
  (`connect-src 'self' <api origin>`) implied a cross-origin browser→API topology without ever
  specifying the CORS or proxy mechanism that would make it buildable. The gap surfaced during
  the build as T3/T5's "most likely integration surprise", and ADR-009 compounded it by claiming
  an `Origin` check that no section actually specified.
  **ROOT CAUSE:** Each service's security surface was designed in isolation; no single concrete
  browser request was ever walked end-to-end across the dev topology (ports, origins, headers)
  before the document was issued.
  **RULE:** Before issuing an architecture, trace at least one *mutating* browser request across
  every trust boundary at real addresses and ports, and verify every mechanism it needs is named
  in the config inventory. Never state a control in an ADR that is not specified in the section
  that owns its implementation.

## Conventions

- Rulings that change a decision are recorded as a **new ADR plus an amendment log entry**, not
  by silently editing the original. ADR-011 (same-origin proxy) supersedes the implied CORS
  topology; ADR-009 was marked amended rather than rewritten.
- Every ADR names its rejected alternatives. An ADR without a rejected alternative is not an ADR.
- Deviations from the parent architecture doc are argued in writing and listed in one place, so a
  reviewer can find all of them without reading the whole document.
- Deferred controls are recorded in the threat model with an owning phase, so no document ever
  claims a control the code does not have.

## Preferences

- The owner (Isuru) approves architecture quickly when the trade-off is named and the rejected
  options are visible. Gate 2 passed in one round trip.
- Engineers on this team escalate rather than invent when a decision needs a document change —
  answer them with an exact config name and default, not a direction.

## Project context reset — 2026-08-13

- SUNIL was re-planned onto the owner-supplied `docs/ROADMAP.md` (Python/FastAPI + Next.js,
  Model Router, Central Orchestrator, agent + tool + permission framework). The NestJS
  architecture and its ADRs are archived at tag `archive/v0-typescript-foundation` and do not
  bind V1 — but L-001 (trace one mutating browser request across every trust boundary at real
  addresses and ports before issuing an architecture) does, and applies harder here: V1 adds an
  LLM provider boundary and a tool-execution boundary on top of browser→API.
- Roadmap §33 lists twelve non-negotiable design rules. Any architecture that contradicts one of
  them needs an ADR arguing it explicitly, not silence.
