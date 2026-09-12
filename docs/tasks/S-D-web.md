# S-D-web — Stream D frontend (Next.js ops dashboard)

**Branch:** `task/S-D-web` · **Owner:** frontend_engineer · **Status:** build complete for the
approved package; render + component tests green.
**Binding inputs (no redesign):** `docs/design/V2_DASHBOARD_SPEC.md`,
`V2_DESIGN_DECISIONS.md` D1–D17, `DESIGN_SYSTEM.md` Amendment A (round-3 values),
`docs/design/mockups/00`–`06`.
**Contracts consumed:** `docs/contracts/C4-approvals-openapi.yaml` (approvals, decisions),
`docs/contracts/C6-ops-reads-openapi.yaml` v1.0.0 FROZEN (tasks, activity, audit).

---

## 1. What is built

| Surface | Route(s) | Mockup |
|---|---|---|
| Nav shell (rail, top bar, skip link, breadcrumbs, stale banner) | all | 06 |
| Dashboard landing (`<details>`/`<summary>` section boxes + `Open full view →`) | `/` | 00 |
| Approvals queue (7-column `DataTable`, one primary link per row, no decisions in a list) | `/approvals` | 01 |
| Approval card (arm-then-commit, two named clocks, containment, 409 handling) | `/approvals/{id}` | 02 |
| Agent activity (running / parked / recent) | `/activity` | 03 |
| Tasks (8-column table, filters) | `/tasks`, `/tasks/{id}` | 04 |
| Audit browser (index + trace, spine + continuation segment) | `/audit`, `/audit/{id}` | 05 |
| Projects, chat (parked-turn view), settings (data-source flag) | `/projects`, `/chat`, `/settings` | — |

**Data layer.** `src/lib/api.ts` is the single client. `dataSource()` returns `mock` by default;
`NEXT_PUBLIC_SUNIL_DATA_SOURCE=api` or the `/settings` toggle (`localStorage['sunil.dataSource']`)
flips **every** read and the decision POST to `NEXT_PUBLIC_API_BASE_URL` with
`credentials: "include"` + `X-SUNIL-Client: web` (ADR-008). No component knows which is in play.
Mock fixtures are the Codely world (EasyClean, PDA, 925, SUNIL) in `src/lib/mock/fixtures.ts`.

## 2. C6 reconciliation (2026-09-12) — drift found and removed

The views were first built against spec §13 before C6 froze. On merging C6 v1.0.0 three real
drifts were found in the mock layer and fixed; `src/lib/mock/c6-conformance.test.ts` now pins the
frozen `required:` key sets exactly (extra keys fail, not just missing ones):

| # | Drift | Resolution |
|---|---|---|
| 1 | `Task.priority` typed `number \| null` | C6 freezes a trusted **string** (`"normal"`). Type corrected; every fixture task now carries it. |
| 2 | `AuditTurn.conversation_label` — **invented by the mock**, not in C6 | Removed from the type, the fixtures and both views. See fidelity note **D-F3**. |
| 3 | `AuditEvent.task_id`, `ActivityItem.latest_*`, `AuditTrace.approval_events` typed optional | C6 house style is *always present, absence is null*. All made required-nullable. |

Two C6 laws the mock did not implement and now does: §2.1 ordering (`created_at desc, id desc`,
plain-string id compare; audit on `started_at desc, request_id desc`) and §2.1 rule 3
(`next_cursor` is null **only** on a short page — an exactly-full final page returns a cursor, so
the views must tolerate one). Reads are deep-copied per the C6 §6/F1 fake rule.

`ProjectSummary` stays on C5/§13.4 — explicitly out of C6 scope (C6 §7).

## 3. Fidelity deviations from the mockups (recorded, for review)

| Id | Deviation | Why |
|---|---|---|
| D-F1 | Mockups are static HTML with hard-coded strings; the app renders fixture data, so figures/timestamps differ from the mockup screenshots (relative times tick). | Live data was always the intent; the mockup numbers are illustrative. |
| D-F2 | Dashboard section titles are styled `<span>`s inside `<summary>`, not `<h2>`s. | `<summary>` owns the expanded-state semantics (§16.6); a nested heading duplicates the accessible name. Flagged for the designer — if heading navigation is wanted, it is a one-line change. |
| D-F3 | **Audit index "Conversation" column and the dashboard audit rows show `conversation_id` (mono, truncated), not a human conversation title.** Mockup 05 shows a title. | C6 freezes no label field on `AuditTurn`. Rendering an invented label would have broken on the day the API flag flips. **Needs an Architect/owner ruling:** add `conversation_label` to C6, or accept the id. |
| D-F4 | Chat is a parked-turn view only (no live streaming composer). | Spec §11 scope for this stream; sending is out of Stream D's exclusive files. |
| D-F5 | Mockup gold glow on the dashboard key figure is `text-shadow`, not the mockup's layered filter. | Amendment A's budgeted-metallic rule — one cheap effect, no per-frame cost. |

## 4. Behaviours pinned by tests (not by hand)

- **Untrusted containment** (`UntrustedText.test.tsx`, 6): HTML/markdown/URL text in
  `summary`/`objective` renders as a **text node only**, never markup, never an attribute —
  probed with the hostile fixture string. C6 §4 / C4 §4.
- **Arm-then-commit** (`DecisionBar.test.tsx`, 12): the decision machine (`src/lib/decision.ts`,
  10 further tests) — arming sends nothing, `R`/`A` arm but a bare keystroke never commits,
  `Escape` disarms (an in-flight decision cannot be cancelled), no optimistic status
  (`Approving…`, never `Approved`), both decisions disabled while the poll is stale, and a 409
  renders the server's `current_status` **verbatim** while applying nothing.
- **Render smoke** (`views.smoke.test.tsx`, 6): the three mockup-complete views (00/01/02) and the
  three C6-backed views (03/04/05) render against the mock fixtures with **zero `console.error` /
  `console.warn`** — the assertion that catches key/hydration warnings a screenshot pass cannot.

**Totals: 38 tests, 5 files, green twice.** `next build` clean, `eslint` clean, `tsc --noEmit` clean.

## 5. Open / handover

- **D-F3 needs a ruling** (see above) — the only user-visible consequence of the C6 freeze.
  **RULED 2026-09-12 (wave-1 R4, `docs/tasks/integration-w1-rulings.md`): keep the raw id for v1** —
  C6 stays 1.0.x; `conversation_label` is a v1.1.0 additive candidate for the audit-UX round (it
  needs the task→conversation join, and `conversations.title` is nullable, so a label can only ever
  supplement the id). No web change owed this wave.
- Reduced motion: `prefers-reduced-motion` kills the pulse and shimmer globally in
  `globals.css`; the live dot also freezes to a static ring when the poll is stale (a glow may
  only claim liveness that is real).
- Not attempted in this stream: real API smoke (no API yet), visual regression, mobile (Q8 open).
