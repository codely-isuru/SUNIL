# Current Architecture

_Assessment date: 21 July 2026_

## Repository state

The `codely-isuru/SUNIL` repository at the time of assessment contained a single
`README.md` and no application code. There is no existing frontend framework,
backend, database, ORM, authentication, agent runtime, job queue, test suite or
Docker configuration to reuse or migrate.

The only existing "product" is a pair of prototype dashboards built as Cowork
live artifacts, now committed under `prototype/`:

| File | Purpose |
|---|---|
| `prototype/jarvis-command-centre.html` | Original J.A.R.V.I.S-themed dashboard |
| `prototype/sunil-command-centre.html` | Rebranded S.U.N.I.L version (current) |

## Prototype analysis

Both prototypes are single self-contained HTML files (~14 KB) with no build
step and no server. What they contain:

### Working, reusable elements

* **Visual identity** — cyan-on-dark HUD aesthetic, Orbitron / Share Tech Mono
  typography, panel styling, status lamps, stat tiles, scanline/vignette
  overlays. This is the seed of the SUNIL design language and should be
  extracted into design tokens (see `SUNIL_ARCHITECTURE.md` §UI).
* **Canvas scene** — an animated fibonacci point-sphere (680 points), rotating
  HUD arcs and an orbital ring, with a "speaking" pulse state. Reusable as the
  dashboard centrepiece / assistant presence indicator.
* **Layout** — a 3-column HUD grid (systems panel, centre stage, content queue
  + tasks) with a bottom metric bar, and a working mobile breakpoint.
* **"Brief Me" interaction** — plays a local `sunil_brief.mp3` if present,
  otherwise falls back to browser `speechSynthesis` with an en-GB voice
  preference. A useful pattern for the voice-output delivery adapter.
* **Live clock** — `Australia/Melbourne` time via `toLocaleTimeString`.

### Limitations (why the prototype cannot be extended in place)

* **All data is hard-coded** in an inline `window.SUNIL_DATA` object
  (greeting, connector states, content queue, tasks, metrics). Nothing is
  fetched; the connector lamps (Gmail, RevenueCat, Metricool, Meta Ads,
  Browser, Routines) are cosmetic.
* **No backend, no persistence, no auth** — nothing to secure, nothing stored.
* **No componentisation** — styling and markup are monolithic; strings are
  injected with `innerHTML` (an XSS hazard the moment data becomes dynamic).
* **Time zone mismatch** — the clock is pinned to `Australia/Melbourne`;
  SUNIL's owner operates on `Australia/Hobart`.
* **Connector list mismatch** — the prototype's connectors (RevenueCat,
  Metricool, Meta Ads) do not match the actual SUNIL integration targets
  (Microsoft Graph, Jira, Teams, weather, Codely/Ezy Clean mailboxes).

## Reuse decision

| Prototype element | Decision |
|---|---|
| Design language (colours, type, panels, lamps) | **Reuse** as design tokens |
| Canvas sphere + HUD arcs | **Reuse** as a React component |
| Dashboard layout | **Reuse** as the Dashboard page skeleton |
| Voice fallback pattern | **Reuse** in the voice delivery adapter |
| Inline `SUNIL_DATA` | **Replace** with real APIs |
| `innerHTML` templating | **Replace** with framework rendering (escaped) |
| Hard-coded connectors/metrics | **Replace** with integration + metrics APIs |
| Melbourne clock | **Replace** with configurable time zone (default Hobart) |

Nothing is deleted: both prototypes are preserved verbatim under `prototype/`
as the design reference and origin of the product.

## Consequence for planning

Because there is no existing stack, SUNIL is a green-field build. The stack
choice, target architecture and phased plan are documented in
`SUNIL_ARCHITECTURE.md` and `IMPLEMENTATION_PLAN.md`. All "inspect before
changing" rules from the project brief have been satisfied by this assessment.
