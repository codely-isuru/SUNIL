# SUNIL — Dashboard Direction (M8 forward sketch)

**Status: M8 direction, NOT M1 scope.** This is a short sketch so the M1 chat build
(`M1_CHAT_SPEC.md`) doesn't get built into a dead end — it is explicitly **not** a spec an
engineer should implement now. Nothing here is developer-ready; treat every section as
provisional until it is its own Gate-reviewed spec, scheduled per `docs/REQUIREMENTS_V1.md`
§2 (M8, depending on M2–M7 APIs landing incrementally).

Traces to: `docs/ROADMAP.md` §6 ("dashboard, chat, and voice are not separate AI systems — they
are separate ways of communicating with SUNIL"), §10 (dashboard contents), FR-160–162.

---

## 1. The shell chat sits inside

```
┌───┬──────────────────────────────────────────────────────────┐
│ S │  Home   Chat   Tasks   Agents   Workflows   Approvals ⋯   │  ← top bar / breadcrumb
│ ‖ ├──────────────────────────────────────────────────────────┤
│ ⌂ │                                                            │
│ 💬│                    (active view renders here)              │
│ ✓ │                                                            │
│ ▣ │                                                            │
│ ⚙ │                                                            │
│ ⚑ │                                                            │
│ 🗓│                                                            │
│ ⋯ │                                                            │
└───┴──────────────────────────────────────────────────────────┘
  ↑
narrow icon rail (collapsed by default, labels on hover/expand)
```

A left icon rail (not a wide sidebar — this is a single-user tool, not a multi-tenant SaaS with
deep navigation needs) lists the §10 destinations: Home, Chat, Tasks, Agents, Workflows,
Approvals, Projects, Calendar, Notifications, Activity Log, Settings. Same `canvas`/`surface`
token palette as chat; same `elevation`/`radius` language for panels.

## 2. Where M1's chat components land, unchanged

`FR-161` requires the dashboard's Chat view to provide the same conversational capability as the
M1 standalone chat (`FR-003`). The intent here: **the M1 chat components are not rebuilt** for
the dashboard — they're the same `MessageList` / `Composer` / `WorkIndicator` / `AssistantMessage`
/ `TraceDisclosure` components from `M1_CHAT_SPEC.md` §7, just rendered inside the shell's content
pane instead of the full viewport. The only things that change are the outer chrome (icon rail +
breadcrumb replace the standalone `TopBar`) and, once M2 lands, the addition of a conversation
list so Chat is no longer single-conversation. If the M1 build couples chat's components tightly
to "full viewport, no chrome," that coupling will need undoing later — worth keeping the
components chrome-agnostic from the start.

## 3. Home overview (§10 "today's overview")

A condensed composite, reusing existing pieces rather than inventing new visual language:

- **Recent conversation** — a preview card showing the last chat turn (reuses `AssistantMessage`
  in a compact/truncated mode).
- **Running agents** — reuses the `WorkIndicator` visual family (phase label + elapsed time +
  glow) as a list of concurrent in-flight or recent tasks, once M1's "one task at a time"
  constraint is lifted by later milestones.
- **Pending approvals** (M5) — a card list using the same `surface`/`radius-md`/border language
  as `ErrorCard`, but with `Approve`/`Reject` actions instead of `Retry`/`Edit`. Visually it's
  the same family: title, short context line, two actions. Not designed further here — flagged
  so M5's designer (or this same designer, later) starts from a consistent shape rather than a
  blank page.
- **System health / connector status** — directly reuses the prototype's `StatusDot`
  ("lamp") pattern already specified in `DESIGN_SYSTEM.md` and used in M1's `TopBar` session
  indicator.

## 4. Where the animated point-sphere motif belongs

`DESIGN_SYSTEM.md` §0 deliberately excludes the prototypes' animated canvas scene from the M1
chat surface (reading-heavy, motion-sensitive, distracting behind text). The Home view is where
it's reserved: a calm, ambient version of it (slower, lower-opacity, ideally reduced-motion-aware
with a static-glow fallback) as a background/hero moment behind the "today" summary — the one
place in the product where the JARVIS/HUD cinematic identity gets to be literal rather than
distilled into flat tokens. This is a suggestion for M8's own design pass, not a commitment.

## 5. Activity Log / debug trace view (NFR-021)

`M1_CHAT_SPEC.md` §5.5's `TraceDisclosure` (the plain-language 12-line reasoning trace shown
per chat turn) is the seed of this. The full Activity Log view is that same list, but
un-scoped to a single turn — searchable/filterable across all requests, with the raw
request/correlation ID (NFR-020) as the join key. Reuse the same "plain English, not raw
JSON/log lines" rendering rule established in the chat spec.

---

**Do not build any of this for M1.** This document exists solely so M1's chat components are
built as chrome-agnostic, reusable pieces rather than a one-off full-page screen that would need
tearing apart when M8 arrives.
