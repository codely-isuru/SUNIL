# ADR-011 — One installable `sunil` package under `apps/api`, preserving roadmap §20's decomposition

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §20, `docs/ARCHITECTURE_V1.md` §2.

## Context

`ROADMAP.md` §20 proposes `core/`, `providers/`, `agents/`, `tools/`, `memory/`, `voice/` as
**top-level sibling directories** alongside `apps/api/` and `apps/web/`. The decomposition is right —
it maps exactly onto §7–§13's component boundaries. The *rooting* is the question.

## Decision

**Adapt.** Keep every §20 boundary, name-for-name; root them all inside one installable Python
package, `sunil`, living at `apps/api/sunil/`. So `sunil.core.orchestrator`,
`sunil.providers.anthropic`, `sunil.tools.github`. One `pyproject.toml`, one `pip install -e .`.

`config/`, `infra/`, `docs/`, `scripts/` remain top-level as §20 has them. `voice/` and
`memory/{embeddings,retrieval,documents}` are **not created** in M1 — they arrive with M9/M7.

Three sub-decisions, each a rename that removes a real ambiguity:

- `core/models/` → **`core/routing/`** — "models" already means ORM tables (`sunil.db.models`); two
  things called models one import apart is a defect generator.
- `core/agents/` → **`core/agent_framework/`**, `core/tools/` → **`core/tool_framework/`** — §20 has
  both `core/agents/` and a top-level `agents/`, which is genuinely ambiguous. Framework vs
  implementation is now visible in the name.
- Backend tests live at **`apps/api/tests/`**, not top-level `tests/` — one pytest rootdir, all
  config in one `pyproject.toml`. §20's top-level `tests/` is reserved for cross-service e2e, created
  when there is a second service to cross (M2+).

## Rejected alternatives

| Rejected | Why |
|---|---|
| **§20 literally: five top-level import roots** | Requires `sys.path` manipulation or five editable installs; `core`, `agents`, `tools` and `memory` are all real PyPI package names, so a namespace collision is a live risk; and circular imports between sibling roots are invisible to tooling until runtime. |
| **A flat `sunil/` with no sub-packages** | Discards §20's decomposition, which is the part of §20 that is right. Also makes the deterministic/LLM boundary invisible in the file tree. |
| **A src-layout monorepo with separate installable packages per component** (`sunil-core`, `sunil-providers`, …) | Genuinely correct for a large team; here it means six `pyproject.toml` files and version-pinning between components that always release together. Overhead without benefit. |
| **Backend at repo root, frontend in `web/`** | Would work, but §20's `apps/{web,api}` split is explicit and it keeps the root readable. Adopted as written. |
| **Creating all §20 directories now, empty, as placeholders** | Empty directories are noise, they do not survive git anyway without a sentinel file, and they imply capability that does not exist. |

## Consequences

- Every deviation is listed in one place, `ARCHITECTURE_V1.md` §16 (V-1 … V-3), so a reviewer can
  find them without reading the whole document.
- `core/` must not import from `sunil.api` — enforced by a lint rule or an import-walking test.
  Without it, the layering in §3.1 decays.
- If a component ever needs to ship independently (unlikely before V3), it can be extracted; nothing
  here forecloses that.
