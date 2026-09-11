# Task — P0-ui-design: V2 ops-dashboard UX/UI design (Gate 2 pack)

Owner (uiux_designer) · Status: **in-review** (handed to the Delivery Manager for owner Gate 2)
**File ownership** (paths only this task may touch): `docs/design/V2_DASHBOARD_SPEC.md`,
`docs/design/V2_DESIGN_DECISIONS.md`, `docs/design/mockups/**`, `docs/design/DESIGN_SYSTEM.md`
(**append-only** — Amendment A at the end; nothing above it altered), `docs/tasks/P0-ui-design.md`.
No app code. No other doc touched.

## Static spec (from the Team 21 brief)

- **Background.** The owner wants to approve the UI before any frontend code exists. Stream D
  (`V2_DEVELOPMENT_PLAN.md`) owns approvals + the ops dashboard; the M1-era design language
  (`DESIGN_SYSTEM.md`, `DASHBOARD_DIRECTION.md`, `M1_CHAT_SPEC.md`) is owner-approved and must be
  evolved, not replaced.
- **Objective.** A developer-ready spec, static mockups for six surfaces, and a short decision log,
  all reviewable by the owner in one sitting and implementable by Stream D without re-deriving
  anything from the contracts.
- **Functional scope.** Nav model uniting chat + five ops views (approvals queue, agent activity,
  tasks, projects, audit browser); per-view layout, four-plus states, element→contract-field map;
  the approval decision surface incl. C4 §4 plain-text containment, expiry/grace, decision flow;
  accessibility (focus order, keyboard approve/refuse, colour-independent status).
- **Acceptance criteria.** Spec keyed to `DESIGN_SYSTEM.md` tokens; every rendered element traced
  to a named contract field or flagged as missing-API; six self-contained mockups with light+dark
  and realistic Codely data; 5–10 numbered decisions each with a rejected alternative; open
  questions surfaced for the owner.
- **Security considerations.** C4 §4 is the binding rule: `summary` and `params_redacted` render as
  plain text only; the design adds visible containment + provenance labelling so the rule is
  legible, not just mechanical. No optimistic UI on decisions (C4 §5). Stale-poll data disables
  decision controls. No secrets anywhere in mockups — all example data is invented.
- **Rollback.** Documents only — revert the branch.
- **Documentation needs.** This is the documentation.

## Cross-lane consumers

- `docs/design/V2_DASHBOARD_SPEC.md` + `mockups/**` → consumed by **Stream D** (frontend build) and
  by the Architect (§13 names three endpoints Phase 0 did not freeze).
- `docs/design/DESIGN_SYSTEM.md` Amendment A → consumed by **any** stream touching `apps/web`
  (new light-theme + status tokens; the Tailwind config gains a theme map if the owner accepts Q7).
- Open questions Q1/Q2/Q9 → **Solution Architect**; Q3/Q5 → **Architect + Security**;
  Q4/Q6/Q7/Q8 → **owner**.

## Deliverables

| File | What |
|---|---|
| `docs/design/V2_DASHBOARD_SPEC.md` | The developer-ready spec: IA, nav, per-view layout + states + field maps, accessibility, required-but-missing endpoints, 9 open questions, traceability |
| `docs/design/V2_DESIGN_DECISIONS.md` | 11 numbered decisions, each with rationale + rejected alternative |
| `docs/design/DESIGN_SYSTEM.md` | **Amendment A appended** (light theme map with computed ratios, status/untrusted/table tokens, ops density scale, tabular figures). Nothing above the amendment line changed |
| `docs/design/mockups/01-approvals-queue.html` | Queue + 4 state variants |
| `docs/design/mockups/02-approval-card.html` | The decision surface + 8 flow states, with a deliberately hostile example `summary` |
| `docs/design/mockups/03-agent-activity.html` | Now / waiting on you / recently finished + states |
| `docs/design/mockups/04-tasks-projects.html` | Tasks table + task detail timeline + projects grid + states |
| `docs/design/mockups/05-audit-browser.html` | Index + a full 12-stage trace (expandable) + the parked-episode continuation segment |
| `docs/design/mockups/06-nav-shell.html` | The shell with chat inside it, the parked-turn card, expanded rail, mobile bottom bar, keyboard model |

All mockups are single files, inline CSS, no JS, Google Fonts only (Orbitron / Share Tech Mono /
JetBrains Mono — the three fonts `DESIGN_SYSTEM.md` §2 already specifies), and follow the OS
light/dark preference.

## Progress

- [2026-09-11 | uiux_designer] Read the owner-approved design language (`DESIGN_SYSTEM.md`,
  `DASHBOARD_DIRECTION.md`, `M1_CHAT_SPEC.md`), `ARCHITECTURE_V2.md` §2/§4/§6, the Stream D scope in
  `V2_DEVELOPMENT_PLAN.md`, C4 (rationale + OpenAPI) and C5 (rationale + OpenAPI), plus
  `ARCHITECTURE_V1.md` §3.4/§7.3 for the twelve stage names, contracted `detail` keys and the
  `tasks`/`audit_events` column shapes the ops views read from.
- [2026-09-11 | uiux_designer] Wrote the spec, the decision log, Amendment A and all six mockups.
  Handed to the Delivery Manager to commit (designer has no shell by design) and to route to the
  owner for Gate 2, and to the Architect for Q1/Q2/Q9.
- **Finding worth the Architect's attention before build:** three of the five ops views
  (activity, tasks, audit) have **no HTTP contract** — `ARCHITECTURE_V2.md` §2 lists only
  `auth/health/chat/approvals/conversations/projects` routes, while Stream D's exit criteria assume
  a tasks view and an audit browser reading `audit_events`. Spec §13 proposes the three minimal
  read-only shapes; Q1 asks whether to freeze them or cut those views from Stream D's first release.

## Open questions for the owner's design review

Full table with defaults in `V2_DASHBOARD_SPEC.md` §14. Short form:

1. **Q1 (blocker, Architect).** Freeze `GET /api/v1/tasks`, `/activity`, `/audit` (spec §13), or cut
   those three views from Stream D v1?
2. **Q2 (Architect).** `tasks` has no `project_key`; add the column, or accept no project filter?
3. **Q3 (Architect).** Expose `SUNIL_APPROVAL_CONSUME_GRACE_HOURS` to the UI, or let the dashboard
   hardcode "1 hour"? (Hardcoding drifts silently if the env var changes.)
4. **Q4 (owner).** Should approvals carry a risk/impact classification? Today a $4,000 refund and a
   label change look identical in the queue until opened.
5. **Q5 (Security).** Is text-node rendering + no linkification + `unicode-bidi: plaintext` the
   accepted containment set, or do you also want a character policy at park time?
6. **Q6 (owner).** Land on Approvals when something is pending (my default), or always on Chat?
7. **Q7 (owner).** Light theme at all — or is SUNIL dark-only as a brand position? (Deleting
   Amendment A §A.2 costs nothing now and a repaint later.)
8. **Q8 (owner).** Is deciding an approval from a phone a v1 requirement?
9. **Q9 (Architect).** Does a parked turn emit all twelve stages or short-circuit after stage 9?

## Issues

<!-- Review findings land here: `file:line` — blocker / should / nit — finding. -->
- *(none yet — awaiting review)*

## Outcome

- PR: — · Commits: (DM commits this lane by path) · Test evidence: n/a (design artefacts; visual
  review is the evidence — open each mockup in a browser and toggle the OS theme) · Notes: not
  self-approved; Gate 2 is the owner's, and any reviewer findings come back here as Issues.
