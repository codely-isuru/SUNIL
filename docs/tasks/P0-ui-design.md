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

All mockups are single files, inline CSS, no JS, Google Fonts only. **Round 2:** the fonts are now
Space Grotesk / Inter / JetBrains Mono (Amendment A §A.5) and every mockup ships a **single
committed dark theme** — Obsidian & Gold, no `prefers-color-scheme` query, every colour painted,
body background explicit (owner's Gate-2 ruling; supersedes the round-1 "follow the OS preference"
line above).

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

### Round 2 — owner-directed visual rework (2026-09-11)

- **Owner's Gate-2 verdict (verbatim intent):** *"Modern styled, futuristic design. Easy to work
  with, all the info displayed properly. Dark mode where it looks and feels like a futuristic
  design. I like black and gold, dark yellowish colors on the dashboard."* Ruling: the round-1
  **skin** was rejected, the **bones** (IA, six views, Decisions 1–9 and 11) were not. Q7 is
  answered: dark-only is the brand position.
- [2026-09-11 | uiux_designer] **Replaced `DESIGN_SYSTEM.md` Amendment A wholesale** (it was
  PROPOSED and unapproved; nothing above the amendment line touched): new "Obsidian & Gold"
  instrument theme — layered blacks `#000000/#12100B/#1C1913/#282318` (elevation by lightness, no
  shadows), gold ramp `#F0B429` accent / `#FFCB57` hover / `#D69C1E` pressed / `#C9971F` ochre /
  `#A89A7E` sand muted / `#161006` on-fill ink, hue-separated status colours (pending `#FF9E45`,
  approved `#6EA8FE`, consumed `#43C878`, refused `#FF6B5E`, expired sand), gold-discipline and
  atmospherics-budget rules, Space Grotesk / Inter / JetBrains Mono type system, density rules,
  full computed contrast table (worst pair 4.8:1, most 7–18:1), Tailwind snippet. Light-theme map
  deleted.
- [2026-09-11 | uiux_designer] **`V2_DESIGN_DECISIONS.md`:** D10 replaced (dark-only committed —
  rejected alternative: a dormant light map); added D12 (palette discipline + status hue
  separation — rejected: monochrome gold HUD), D13 (type choices — rejected: keep Orbitron /
  all-mono body), D14 (density: summary rails, both timestamps at rest, nothing readable behind
  hover — rejected: round-1 progressive disclosure), D15 (atmospherics budget: hairlines, corner
  ticks, ≤2% scanline on the void, glow only on armed/live — rejected: animated backgrounds and
  flat zero-atmosphere).
- [2026-09-11 | uiux_designer] **`V2_DASHBOARD_SPEC.md`:** token references updated (§ header,
  §2 NavRail, §3 type/theme/density bullets, §12.4 contrast table re-derived for the new grounds,
  Q7 marked ANSWERED, §15 traceability). All interaction/security content untouched.
- [2026-09-11 | uiux_designer] **All six mockups regenerated** in the new system — same filenames,
  self-contained, inline CSS, no JS, Google Fonts only, single explicit dark theme (no
  `prefers-color-scheme`), same realistic Codely data. The parked stripe.refund card remains the
  money screen; the C4 §4 untrusted-text quotation pattern survives restyling (sand-barred,
  mono-set, provenance-labelled). New per-view summary rails; relative + absolute timestamps at
  rest; audit collapsed rows now carry key figures inline; the armed decision control and the live
  WorkIndicator are the only glowing elements.
- **Skill note:** the brief asked for a components skill named "impeccable", which is not
  installed; per the task instructions the sanctioned substitutes `ui-ux-pro-max` and `ui-styling`
  were read and applied (dark-mode contrast pairs checked per ground, no hover-only reveals,
  token-driven theming, one primary CTA per screen, reduced-motion kill-switch retained).
- Handed to the Delivery Manager to commit (designer has no shell by design) and to route the
  round-2 package back to the owner for Gate 2.

### Round 3 — owner-directed comfort + effects tuning (2026-09-11)

- **Owner's verdict on the round-2 package (verbatim):** *"the contrast are bit high on these
  designs its hard to keep on the eye for a long time. make it so it got a cool effects. remove
  yellow keep black and gold colors."* Read as three rulings: lower the contrast for long
  sessions, de-yellow the palette (black + gold only), raise the atmosphere tastefully.
- [2026-09-11 | uiux_designer] **Amendment A re-tuned in place** (`DESIGN_SYSTEM.md`; nothing above
  the amendment line touched). Grounds lift off pure black: `#0B0906 / #16120C / #201A11 / #2B2315`.
  Gold de-yellowed to antique/metallic: accent `#C9A227` (8.2:1), hover `#DBBE7F` pale champagne,
  pressed `#A6801F` bronze, deep `#B08A2A`, ink `#14100A`. Text re-tuned into a new **comfort
  ceiling** (§A.7: AA 4.5:1 floor unchanged + sustained-reading text 9–13:1, max 13.5:1): body
  `#CEC5B4` 11.6:1 canvas / 9.1:1 lightest ground (was 18.3:1), headings `#C4B48D` 9.7:1, muted
  `#9A8D71` 6.1/4.7:1. Status de-yellowed and dimmed: pending → **copper** `#D98E4A` (7.5:1, hue
  ≈28° vs gold's ≈46°; distinction rule named in §A.3), approved `#5E96E0`, consumed `#3FAE6C`,
  refused `#E8685C`. Hairlines quieter (.16/.38). Full recomputed contrast table in §A.7 — worst
  text pair 4.7:1, everything in or below the comfort band.
- [2026-09-11 | uiux_designer] **Atmospherics budget §A.4 expanded** (owner's "cool effects"),
  all CSS-only, reduced-motion-safe, never on reading surfaces: panel sheen (≤3% gold
  top-gradient), metallic gradient on gold fills (ink AA at every stop), key-figure text-glow,
  live pulse slowed 1100→2600ms, one shimmer sweep on the armed confirm button. Blur/animated
  backgrounds stay forbidden.
- [2026-09-11 | uiux_designer] **All six mockups regenerated in place** in the tuned system —
  same filenames, self-contained, no JS, single explicit dark theme. Per-file: 01 panel sheen +
  gold key-figure glow; 02 metallic Approve fill + armed shimmer (gold and re-tuned danger
  variants) + sheen on card/minis; 03 slowed gold pulse on the two running cards + sheen + key
  figure; 04/05 sheen + key-figure glow; 06 slowed pulse, re-tinted user bubble, sheen on
  parked/rail panels — chat message bodies deliberately left flat.
- [2026-09-11 | uiux_designer] **`V2_DESIGN_DECISIONS.md`:** D12 amended (de-yellowing + comfort
  ceiling, owner verdict quoted as driver; rejected: darken-gold-only, sub-9:1 body text), D15
  amended (budget raised to eight named items; rejected: point-sphere, glassmorphism, round-2
  flatness), **D16 added** (motion grammar: one 2600ms clock, two moving elements — liveness only;
  rejected: bespoke timings, entrance animations on poll refresh, countdown ring).
- Handed to the Delivery Manager to commit and route the round-3 package to the owner.

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
7. **Q7 (owner).** ~~Light theme at all — or is SUNIL dark-only as a brand position?~~
   **ANSWERED (Gate-2 round 2): dark-only is the brand position.** Light map deleted; Amendment A
   is now the committed Obsidian & Gold theme.
8. **Q8 (owner).** Is deciding an approval from a phone a v1 requirement?
9. **Q9 (Architect).** Does a parked turn emit all twelve stages or short-circuit after stage 9?

## Issues

<!-- Review findings land here: `file:line` — blocker / should / nit — finding. -->
- *(none yet — awaiting review)*

## Outcome

- PR: — · Commits: (DM commits this lane by path) · Test evidence: n/a (design artefacts; visual
  review is the evidence — open each mockup in a browser and toggle the OS theme) · Notes: not
  self-approved; Gate 2 is the owner's, and any reviewer findings come back here as Issues.
