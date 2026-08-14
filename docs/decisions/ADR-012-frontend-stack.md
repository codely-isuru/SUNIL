# ADR-012 — Next.js 16 App Router + React 19 + Tailwind CSS pinned to 3.4.19, as a pure client app

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** `ROADMAP.md` §4 (Next.js/React/Tailwind), `docs/design/DESIGN_SYSTEM.md` §1,
`docs/design/M1_CHAT_SPEC.md` §7, `docs/ARCHITECTURE_V1.md` §12, ADR-008.

## Context

The roadmap names Next.js + React + Tailwind. The Designer's `DESIGN_SYSTEM.md` ships a **Tailwind
v3 `tailwind.config.ts → theme.extend`** block as a paste-in artefact, and `M1_CHAT_SPEC.md` §7
names twelve components that the frontend engineer will create as files.

Current versions on 2026-08-14: `next` 16.3.1, `react` 19.2.8, `tailwindcss` 4.3.3 (latest v3:
3.4.19). Node on this machine is 24.19.0, pnpm 11.8.0.

## Decision

- **Next.js 16 (App Router), React 19, TypeScript, pnpm**, in `apps/web` with its own lockfile —
  deliberately **not** at the repo root, where a ~1.1 GB stale `node_modules/` from the retired
  TypeScript build still sits (`docs/ENVIRONMENT.md` §2).
- **Tailwind CSS pinned to `3.4.19`.** `create-next-app` now scaffolds v4, so the engineer must
  scaffold **without** Tailwind and add `tailwindcss@3.4.19 postcss autoprefixer` explicitly.
- **A pure client application.** No Server Actions, no route handlers proxying the API, no server
  components fetching from FastAPI. `apps/web/src/app/(chat)/page.tsx` is `"use client"`.
- **File names mirror `M1_CHAT_SPEC.md` §7 component names one-for-one**, so a spec section maps to a
  file without translation.
- One hook, `useTurn()`, owns a turn end-to-end and implements both ADR-009 variants (real SSE, and
  the Designer's client-side stepper fallback) behind one interface.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Tailwind v4 (latest)** | The right long-term answer, and where M8 goes. Rejected for M1 because `DESIGN_SYSTEM.md` ships a v3 config block verbatim and translating it to v4's CSS-first `@theme` on day one is an unforced token-drift risk in the exact artefact the Designer told us not to paraphrase. **Debt D-5**, owed at M8. |
| **Vite + React SPA (no Next.js)** | Lighter and arguably better suited to a pure client app. Rejected because `DASHBOARD_DIRECTION.md` puts a multi-view dashboard shell at M8, the roadmap names Next.js, and switching frameworks between M1 and M8 is a worse cost than one unused server runtime now. |
| **Next.js Server Actions / route handlers as a BFF** | Creates a second trust boundary with its own cookie and CSRF surface — see ADR-008's reasoning in full. |
| **Server components fetching the chat API** | A turn is an interactive, cancellable, progressively-updating operation. Rendering it server-side fights every part of `M1_CHAT_SPEC.md` §5.3. |
| **Plain CSS / CSS modules instead of Tailwind** | The design system is expressed as Tailwind tokens; re-expressing it costs a day and drifts. |
| **A component library (shadcn/ui, MUI)** | `M1_CHAT_SPEC.md` specifies twelve bespoke components against a bespoke HUD design language. A library would be fought, not used. |

## Consequences

- **Debt D-5:** Tailwind v4 migration at M8, when the dashboard design pass revisits the token
  contract anyway.
- The stale root `node_modules/` stays untouched and gitignored; `apps/web` is self-contained.
- Because there is no Next server in the request path, ADR-008's trust-boundary walk has exactly one
  browser-side boundary, which is the point.
- `M1_CHAT_SPEC.md` §5.4 names `AssistantMessage`'s body as the M2 token-streaming insertion point;
  keeping the app client-side means that seam needs no structural change.
