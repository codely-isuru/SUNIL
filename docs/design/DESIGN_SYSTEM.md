# SUNIL — Design System (V1 Token Contract)

**Author:** UI/UX Designer, Minions Team 18
**Status:** Ready for Gate 2 review. This is the token contract the frontend engineer implements
in `apps/web` (Next.js + Tailwind CSS).
**Source material (READ-ONLY, not to be edited):** `prototype/sunil-command-centre.html` and
`prototype/jarvis-command-centre.html`. Both files are visually identical (same CSS, same
canvas scene, different title text) — they are one design language, not two, and this document
is the distillation of that language into a token set an engineer can build from without
re-opening the HTML.

---

## 0. What was extracted vs. deliberately adapted

**Extracted directly from the prototypes (kept as-is):**
- Near-black void background, glass panels with a thin cyan hairline border and a small glowing
  "tab" accent top-left of each panel.
- Cyan (`#22D3EE`) as the single accent colour running through headings, borders, glows and the
  active/"speaking" state.
- Amber for time-sensitive/attention items (queue timestamps, warning lamps), green for
  "online/ok", muted red for negative deltas.
- The "lamp" status-dot pattern (coloured dot + text state, never colour alone).
- Orbitron for display type (the wordmark, big numbers, panel micro-headings) — geometric,
  letter-spaced, uppercase.
- A monospace body font, because SUNIL reads as an operator's terminal/HUD, not a consumer app.
- Soft glow-as-elevation instead of grey drop-shadows — this system has no neutral shadow scale,
  elevation *is* glow intensity.

**Deliberately adapted (and why — flagged so no one thinks it was missed):**
- **The prototypes' exact `cyan-dim` (55%-opacity cyan) used for small label text fails WCAG AA**
  at the sizes it's used at in the prototype (~3.9:1 computed, see §7). This system defines a
  **solid** `text-muted` token tuned to clear 4.5:1 instead of reusing that opacity value for any
  text a user must read. The opacity-based dim cyan is kept, but only for **decorative borders**,
  where the contrast requirement is relaxed (non-text, 3:1 against adjacent surfaces, still met).
- **Share Tech Mono ships in one weight only (400, no bold, no italic).** It is kept for short HUD
  chrome strings (labels, timestamps, status rows) where no emphasis is ever needed. For the
  chat body font — which must render assistant markdown (**bold**, lists, code) — this system
  specifies **JetBrains Mono** instead, matching the same monospace HUD identity but with the
  weight range a real conversation needs. Nobody but this document decided that; it's recorded
  here so it isn't rediscovered as a bug in build.
- **The animated point-sphere / scanlines / vignette full-screen canvas is not used behind
  reading-heavy screens (chat).** It's a beautiful ambient/idle moment but actively hurts legibility
  and fights `prefers-reduced-motion` when it sits behind body text for minutes at a time. It is
  reserved for an ambient/ "Home" dashboard moment (M8 — see `DASHBOARD_DIRECTION.md`), not
  spent on M1. The chat surface keeps the *palette* and *panel language*, not the moving scene.

---

## 1. Colour Tokens

All tokens below are solid hex values unless explicitly marked "decorative/non-text". Use solid
values for anything text sits on or reads as; reserve opacity for borders/glows only.

| Token | Hex / value | Role |
|---|---|---|
| `--color-canvas` | `#030712` | Page background ("the void"). Matches prototype `--bg`. |
| `--color-surface` | `#0B1220` | Panel/card background (solid — replaces the prototype's translucent `rgba(7,16,32,.72)` panel fill so text on panels has a guaranteed, computable contrast ratio instead of one that shifts with whatever is behind it). |
| `--color-surface-raised` | `#111B2E` | Inputs, code blocks, hovered rows — one step up from `surface`. |
| `--color-border` | `#1E2A3E` | Default structural divider/border (list rows, panel edges where no glow is wanted). |
| `--color-border-accent` | `rgba(34,211,238,.18)` | Decorative panel border, matches prototype `--cyan-faint`. Non-text use only. |
| `--color-border-strong` | `rgba(34,211,238,.4)` | Hover/focus-adjacent decorative border upgrade. Non-text use only. |
| `--color-accent` | `#22D3EE` | Primary brand/interactive colour. Links, active icons, primary button fill, focus ring core. |
| `--color-accent-hover` | `#67E8F9` | Hover/lighter variant (matches the prototype's starfield highlight colour). |
| `--color-accent-active` | `#06B6D4` | Pressed state for accent-filled controls. |
| `--color-accent-on` | `#031015` | Text/icon colour placed **on top of** a solid accent fill (e.g. primary button label). |
| `--color-text-primary` | `#E8FBFF` | Default body text — chat messages, primary content. |
| `--color-text-secondary` | `#7DD3FC` | Headings, panel micro-labels, emphasis (matches prototype `.panel h2` colour). |
| `--color-text-muted` | `#4FA8C7` | Meta text: timestamps, placeholder copy, secondary captions. Solid, AA-verified (§7) — **do not** substitute the prototype's opacity-based dim cyan here. |
| `--color-text-disabled` | `#2E4256` | Disabled control label. (WCAG does not require contrast on disabled controls, but this stays visually distinct from `surface`.) |
| `--color-success` | `#34D399` | "Online"/allowed/positive delta. |
| `--color-warning` | `#FBBF24` | "Standby"/attention/time-sensitive. |
| `--color-danger` | `#F87171` | "Offline"/error text and icons. |
| `--color-danger-strong` | `#EF4444` | Danger button fill (paired with white/`--color-accent-on`-class text). |

### Tailwind config (paste into `tailwind.config.ts` → `theme.extend`)

```ts
colors: {
  canvas: "#030712",
  surface: { DEFAULT: "#0B1220", raised: "#111B2E" },
  border: { DEFAULT: "#1E2A3E", accent: "rgba(34,211,238,.18)", strong: "rgba(34,211,238,.4)" },
  accent: { DEFAULT: "#22D3EE", hover: "#67E8F9", active: "#06B6D4", on: "#031015" },
  text: {
    primary: "#E8FBFF",
    secondary: "#7DD3FC",
    muted: "#4FA8C7",
    disabled: "#2E4256",
  },
  success: "#34D399",
  warning: "#FBBF24",
  danger: { DEFAULT: "#F87171", strong: "#EF4444" },
},
borderRadius: { sm: "4px", md: "6px", lg: "12px", full: "9999px" },
boxShadow: {
  "glow-hover": "0 0 12px rgba(34,211,238,.25)",
  "glow-active": "0 0 24px rgba(34,211,238,.35)",
  "glow-focus": "0 0 0 3px rgba(34,211,238,.35)",
},
transitionDuration: { fast: "150ms", base: "250ms", slow: "600ms" },
```

---

## 2. Typography

### Font stacks

| Token | Stack | Use |
|---|---|---|
| `--font-display` | `'Orbitron', ui-sans-serif, system-ui, sans-serif` | Wordmark, page/section titles, panel micro-headings, stat numbers. **Decorative only — never body prose.** |
| `--font-mono-ui` | `'Share Tech Mono', ui-monospace, monospace` | Short HUD chrome strings only: status labels, timestamps, badges, connector rows. One weight (400) — never needs bold. |
| `--font-mono-body` | `'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` | Chat messages (user + assistant), composer input, code blocks — anything that must render at length or needs **bold**/`code` emphasis. |

### Scale

| Style | Font | Size / line-height | Weight | Letter-spacing | Use |
|---|---|---|---|---|---|
| Display | display | 34px / 1.1 | 800 | 0.3em, uppercase | Wordmark only |
| H1 | display | 24px / 1.3 | 700 | 0.15em, uppercase | Page/section title |
| H2 | display | 12px / 1.4 | 600 | 0.2em, uppercase | Panel micro-heading (matches prototype `.panel h2`) |
| H3 | mono-body | 13px / 1.4 | 600 | 0.05em, uppercase | Sub-label (e.g. component group headers) |
| Body | mono-body | 15px / 1.6 | 400 | normal | Chat messages, default UI text |
| Body-strong | mono-body | 15px / 1.6 | 600–700 | normal | Emphasis inside a message |
| Small / meta | mono-body | 12px / 1.5 | 400 | 0.02em | Timestamps, captions, status text |
| Micro / badge | mono-ui | 10px / 1.4 | 400 | 0.15em, uppercase | Status chips, lamp labels |
| Code | mono-body | 14px / 1.5 | 400 | normal | Code blocks, in a `surface-raised` container |

Root size is 16px; all values above are intended as rem-equivalent (e.g. 15px = 0.9375rem) —
**use rem, not px**, so the system respects the user's browser text-size setting (§7).

### Tailwind config (paste into `tailwind.config.ts` → `theme.extend`)

**Confirmed against the T14 implementation** (`apps/web/tailwind.config.ts`,
`35f6f2a`) — values verified line-for-line correct against the scale table above. Weight and
`uppercase` are deliberately **not** baked into the size tokens; apply them as ordinary Tailwind
utilities (`font-semibold`, `uppercase`) at the call site, per each row's Weight column above.
`body`/`code` have no `letterSpacing` entry below because their spec value is "normal" —
Tailwind's default, so no token is needed.

```ts
fontFamily: {
  display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
  "mono-ui": ["var(--font-mono-ui)", "ui-monospace", "monospace"],
  "mono-body": [
    "var(--font-mono-body)",
    "ui-monospace",
    "SFMono-Regular",
    "Menlo",
    "Consolas",
    "monospace",
  ],
},
// [fontSize, lineHeight] rem pairs — one entry per row of the scale table above.
fontSize: {
  display: ["2.125rem", "1.1"],   // 34px / 1.1
  h1: ["1.5rem", "1.3"],          // 24px / 1.3
  h2: ["0.75rem", "1.4"],         // 12px / 1.4
  h3: ["0.8125rem", "1.4"],       // 13px / 1.4
  body: ["0.9375rem", "1.6"],     // 15px / 1.6
  small: ["0.75rem", "1.5"],      // 12px / 1.5
  micro: ["0.625rem", "1.4"],     // 10px / 1.4
  code: ["0.875rem", "1.5"],      // 14px / 1.5
},
letterSpacing: {
  display: "0.3em",
  h1: "0.15em",
  h2: "0.2em",
  h3: "0.05em",
  small: "0.02em",
  micro: "0.15em",
},
```

`var(--font-display)` / `--font-mono-ui` / `--font-mono-body` are bound to actual font files via
`next/font/google` in `apps/web/src/app/layout.tsx`: **Orbitron** (weights 400/600/700/800) →
`--font-display`; **Share Tech Mono** (weight 400 only) → `--font-mono-ui`; **JetBrains Mono**
(weights 400/600/700) → `--font-mono-body`. This is the correction from §0 actually landing in
code, not just named correctly — JetBrains Mono carries the 600/700 weights Share Tech Mono
can't, which is the entire reason it was substituted in for body prose.

---

## 3. Spacing

No new scale — use Tailwind's default 4px-based spacing scale directly. Conventions for this
product:

- Chat column max width: `max-w-3xl` (768px), centred (`mx-auto`).
- Panel/card padding: `p-4` (mobile) / `p-6` (desktop).
- Stack gap between messages: `gap-4`.
- Tight list rows (status/queue rows, matches prototype `.sysrow`): `gap-1`, `py-1.5`.
- Page gutter: `px-4` mobile, `px-8` desktop.

---

## 4. Radii

| Token | Value | Use |
|---|---|---|
| `radius-sm` | 4px | Chips, badges |
| `radius-md` | 6px | Buttons, inputs, message bubbles, panels — **matches the prototype exactly.** |
| `radius-lg` | 12px | Larger cards/containers, modals |
| `radius-full` | 9999px | Status dots, avatar, pill buttons |

---

## 5. Elevation (glow, not grey shadow)

This system has no neutral drop-shadow scale. Depth is expressed as **cyan glow intensity**,
matching the prototypes' HUD language.

| Token | CSS | Use |
|---|---|---|
| `elevation-0` (resting) | `border: 1px solid var(--color-border-accent);` | Default panel state |
| `elevation-1` (hover) | add `box-shadow: var(--glow-hover)` | Hoverable panel/button |
| `elevation-2` (active/live) | `box-shadow: var(--glow-active)` | The in-progress "SUNIL is working" indicator, actively-focused input |
| `focus` | `box-shadow: var(--glow-focus)` + `outline: 2px solid var(--color-accent); outline-offset: 2px;` | Any focused interactive element (see §7) |

---

## 6. Motion

| Token | Value | Use |
|---|---|---|
| `duration-fast` | 150ms | Hover/press feedback |
| `duration-base` | 250ms | Panel/state transitions (matches prototype `transition:.25s`) |
| `duration-slow` | 600ms | Message-enter, phase-change transitions |
| `ease-standard` | `cubic-bezier(0.4,0,0.2,1)` | Default easing for all of the above |
| `pulse` | 1100ms, `ease-standard` easing, infinite — matches prototype `@keyframes btnpulse`'s peak value | The "working" indicator's breathing glow **only** |

### Confirmed Tailwind implementation (§6)

**Confirmed against T14** (`apps/web/tailwind.config.ts`, `35f6f2a`). The pulse token's easing
was implemented as `ease-standard` rather than the generic `ease-in-out` keyword this document
originally implied — that's a correct harmonisation (one easing curve system-wide instead of a
one-off) and is adopted here as the confirmed value, not a deviation:

```ts
transitionTimingFunction: {
  standard: "cubic-bezier(0.4,0,0.2,1)",
},
keyframes: {
  "work-pulse": {
    "0%, 100%": { boxShadow: "0 0 24px rgba(34,211,238,.35)" },   // = glow-active
    "50%": { boxShadow: "0 0 44px rgba(34,211,238,.55)" },          // matches prototype btnpulse peak
  },
},
animation: {
  "work-pulse": "work-pulse 1100ms cubic-bezier(0.4,0,0.2,1) infinite",
},
```

Class name in components: `animate-work-pulse`, applied to the `WorkIndicator` card only
(`M1_CHAT_SPEC.md` §5.3) — disabled automatically under `prefers-reduced-motion: reduce` via the
global kill-switch in `globals.css` (see confirmation below), not via a separate no-motion
variant of the class.

**Reduced motion:** under `prefers-reduced-motion: reduce`, the `pulse` loop and any
message-enter slide/fade **must** be disabled or reduced to an instant/opacity-only change
≤150ms. The "working" state must remain visually identifiable without animation — it already is,
via its text label and static glow border, so no information is lost when motion is removed.

---

## 7. Accessibility Floor

This is the non-negotiable baseline. Anything shipped against this design system must meet it.

**Contrast — verified pairs** (WCAG relative-luminance method; canvas `L≈0.00216`,
surface `L≈0.00609`):

| Pair | Computed ratio | Requirement | Result |
|---|---|---|---|
| `text-primary` (#E8FBFF) on `canvas` | ~19.9:1 | 4.5:1 (body) | Pass (AAA) |
| `text-primary` on `surface` | ~17.5:1 | 4.5:1 | Pass (AAA) |
| `text-secondary` (#7DD3FC) on `canvas` | ~12.1:1 | 4.5:1 | Pass (AAA) |
| `text-muted` (#4FA8C7) on `canvas` | ~7.4:1 | 4.5:1 | Pass |
| `accent` (#22D3EE) on `canvas` (links, focus ring) | ~11.1:1 | 3:1 (non-text) / 4.5:1 (if used as text) | Pass either way |
| Prototype's original `cyan-dim` (55%-opacity cyan) used as small label text | ~3.9:1 | 4.5:1 | **Fails** — this is why `text-muted` exists as a solid token instead. Never use opacity-based colour for text a user must read. |

**Rule of thumb for anyone adding a new colour token later:** against this system's near-black
backgrounds, a solid colour needs a relative luminance of roughly **≥0.20** to clear 4.5:1 body
text contrast. Check any new token with a contrast calculator before shipping it as text colour —
don't eyeball it.

**Focus states:** every interactive element gets a visible focus indicator on keyboard focus
(`:focus-visible`) — 2px solid `--color-accent` outline, 2px offset, plus the `glow-focus`
shadow for the HUD feel. Never remove `outline` without supplying this replacement. Mouse/pointer
clicks need not show the ring (`:focus-visible` handles this natively); keyboard users always
get it.

**Confirmed implementation (T14, `globals.css`, `35f6f2a`):** `:focus { outline: none }` paired
with `:focus-visible { outline: 2px solid var(--color-accent); outline-offset: 2px; box-shadow:
var(--glow-focus); }` — matches this spec exactly. Contrast checked against the **lightest**
surface token in the palette (`surface-raised`, `#111B2E`, relative luminance ≈0.011, the
harder case than `canvas`/`surface`): the accent ring computes to **≈9.5:1**, well clear of the
3:1 non-text minimum. The ring remains legible against every surface in this system.

**Reduced motion:** respect `prefers-reduced-motion: reduce` everywhere per §6. No experience may
depend on animation to convey state — motion is always a reinforcement of a text/colour state
change, never the sole carrier.

**Confirmed implementation (T14, `globals.css`):** a global kill-switch —
`*, *::before, *::after { animation-duration: .01ms !important; animation-iteration-count: 1
!important; transition-duration: .01ms !important; scroll-behavior: auto !important; }` under
the media query — collapses `animate-work-pulse` and every transition to effectively instant,
exceeding the "≤150ms" floor this document sets. No per-component reduced-motion variant is
needed as a result; the kill-switch is sufficient and should stay global.

**Keyboard operability:** every control reachable via Tab in logical DOM order; actionable via
Enter/Space; Escape closes any transient overlay (expanded trace panel, etc.); no keyboard traps;
visible focus at every step (see above).

**Text resize / zoom:** all type sized in rem; no fixed-height containers that clip text at 200%
browser zoom or OS-level text-size increase.

**Colour is never the only signal:** status indicators (the "lamp" pattern) always pair a colour
with a text label or distinct icon shape — carried over directly from the prototype, which
already does this correctly (`ONLINE`/`STANDBY`/`OFFLINE` text next to the coloured dot).

**Screen reader baseline:** assistant replies land in a polite `aria-live="polite"` region;
errors/timeouts use `aria-live="assertive"`. Stage-progress updates (see
`M1_CHAT_SPEC.md` §5.3) are throttled to one live-region update per phase change, not per raw
backend stage, so screen reader users aren't spammed with twelve rapid announcements.

---

# AMENDMENT A — V2 "Obsidian & Gold" instrument theme (round 2, owner-directed)

**Replaced wholesale: 2026-09-11 (round 2)** by the UI/UX Designer, Minions Team 21, after the
owner's Gate-2 verdict on the round-1 package: *"Modern styled, futuristic design. Easy to work
with, all the info displayed properly. Dark mode where it looks and feels like a futuristic design.
I like black and gold, dark yellowish colors on the dashboard."*
That verdict **answers spec Q7: SUNIL is dark-only as a brand position.** The round-1 Amendment A
(light-theme map, cyan-derived status aliases) was PROPOSED, was not approved, and is deleted —
not archived. **Nothing above this line was changed.**

Reading of the brief that governs everything below: *futuristic means precision instrument, not
sci-fi kitsch.* The owner operates real approvals with real money on these screens, daily, at 8am.
Futurism is carried by layered blacks, a rationed gold, technical typography and tabular data —
never by decoration that costs legibility.

## A.0 Scope and precedence

- This amendment is the visual language for **every surface rendered inside the V2 shell** — the
  six views of `V2_DASHBOARD_SPEC.md`, including chat, which V2 re-hosts inside the shell. In
  practice every V2 screen is Obsidian & Gold.
- §0–§7 above remain binding for **structure**: the accessibility floor (§7), motion durations and
  the reduced-motion kill-switch (§6), radii (§4), spacing conventions (§3), the lamp pattern, the
  focus-visible rule. Where §1/§2 name a **colour or font** and this amendment names another, V2
  surfaces use this amendment. The cyan/Orbitron values above stay recorded as the approved M1
  contract of record.
- Token **names** are unchanged (`--color-accent`, `--color-text-muted`, …) so every reference in
  `V2_DASHBOARD_SPEC.md` still resolves; only the values move. "Accent" now *means* the gold.

## A.1 Grounds — layered blacks (elevation is lightness, not shadow)

| Token | Hex | L (rel. lum.) | Role |
|---|---|---|---|
| `--color-canvas` | `#000000` | .0000 | The void. True-black page ground. The only surface that may carry the scanline texture (A.4) |
| `--color-surface` | `#12100B` | .0052 | Panels, cards, tables, rail, topbar — warm charcoal, one step up |
| `--color-surface-raised` | `#1C1913` | .0099 | Row hover, untrusted blocks, expanded trace rows, table headers |
| `--color-surface-high` | `#282318` | .0172 | Inputs, code blocks, the highest layer (confirm steps, sheets) |
| `--color-border` | `#2B2416` | .0183 | Structural 1px dividers (non-text; 1.3:1 vs surface — deliberate, like §1's border) |
| `--color-border-accent` | `rgba(240,180,41,.20)` | — | Decorative gold hairline on framed panels. Non-text only |
| `--color-border-strong` | `rgba(240,180,41,.45)` | — | Hover/focus-adjacent hairline upgrade, corner ticks. Non-text only |

**The elevation rule (replaces §5 for V2 surfaces):** depth = one surface step up + a 1px border.
There is **no drop-shadow scale and no glow-as-elevation** in this theme. Glow exists, but it is a
*state* (A.4), never a height. A panel that needs to read "above" another gets a lighter ground,
which is how a physical instrument panel does it.

## A.2 The gold ramp — and the discipline that keeps it precious

| Token | Hex | Role |
|---|---|---|
| `--color-accent` | `#F0B429` | **The gold.** Interactive elements: links, primary button fill, active nav edge, focus ring, the single key figure per view |
| `--color-accent-hover` | `#FFCB57` | Hover lift |
| `--color-accent-active` | `#D69C1E` | Pressed |
| `--color-accent-on` | `#161006` | Ink — text/icons on any gold or status fill (10.4:1 on the gold) |
| `--color-gold-deep` | `#C9971F` | Dark amber/ochre: secondary emphasis — decided-count figures, section accents, "warm" metadata that must not compete with interactive gold (7.9:1 on canvas) |
| `--color-text-primary` | `#F5EFE3` | Body text — warm off-white, not `#FFFFFF` (pure white on true black causes halation glare at night; 18.3:1 is already AAA with room to spare) |
| `--color-text-secondary` | `#DECFA8` | Headings, emphasis, panel titles (13.6:1) |
| `--color-text-muted` | `#A89A7E` | Desaturated sand: meta text, timestamps, labels (7.6:1 canvas / 5.7:1 on the lightest surface — AA everywhere it can legally sit) |
| `--color-text-disabled` | `#5D5442` | Disabled labels (non-text requirement; ~2.1:1 vs `surface-high`, visibly dimmer, clearly not interactive) |

**Gold discipline (normative, not taste):**
1. **Gold is spent, not poured.** Per view: interactive elements + at most **one** key figure (the
   pending count on Approvals, the live phase on Activity, nothing on a reading surface). A page
   drowning in gold is a page with no hierarchy.
2. Gold is **never body text** and never a large area fill except the primary button.
3. **Status is never gold** (A.3). If a status and the brand share a hue, "decided" becomes
   indistinguishable from "clickable".
4. `--color-gold-deep` is the release valve: when something wants warmth but is not interactive,
   it gets ochre, not gold.

## A.3 Status colours — hue-separated from the brand

Round 1 aliased `approved → accent` and `pending → warning(amber)`. Both aliases break under a gold
brand: an amber pending pill would read as a button, and a gold APPROVED pill would read as brand
chrome. V2 statuses are therefore their own hues, each AA on every ground they sit on:

| Token | Hex | On canvas | Meaning | Why this hue |
|---|---|---|---|---|
| `--status-pending` | `#FF9E45` | 10.2:1 | Waiting on the owner. Also `--color-warning` (stale, banners, parked) | Orange — attention, clearly not the yellow gold |
| `--status-approved` | `#6EA8FE` | 8.7:1 | Decided, not yet executed | Signal blue — "cleared to run". Deliberately still not green: approved ≠ done |
| `--status-consumed` | `#43C878` | 9.8:1 | Executed, single use spent. Also `--color-success` | Green stays reserved for *actually happened* |
| `--status-refused` | `#FF6B5E` | 7.5:1 | Owner said no. Also `--color-danger` | — |
| `--status-expired` | `#A89A7E` | 7.6:1 | Timed out, never ran (= `text-muted`) | Neutral on purpose: an expiry is not an error the owner caused |
| `--color-danger-strong` | `#E5484D` | fill | Danger button fill, paired with `--color-accent-on` ink (4.8:1) | — |

Task `in_progress`/RUNNING maps to **gold** deliberately — it is the one status allowed to share
the brand hue, because "SUNIL is alive right now" *is* the live/active state the glow budget (A.4)
exists for. Every status remains icon + uppercase text + colour + edge pattern (spec §12.3);
greyscale-printed rows stay classifiable.

Untrusted-containment and table roles carry over from round 1 unchanged in role, revalued:
`--color-untrusted-bg` = `surface-raised`, `--color-untrusted-bar` = `text-muted` (sand),
`--color-row-hover` = `surface-raised`, `--color-redacted` = `text-disabled`. The containment is
carried by the left bar + provenance label, not by a novel colour — unchanged from Decision 3.

## A.4 Light is a state; texture is a whisper (the atmospherics budget)

Permitted, and only these:
- **Hairline gold rules** — 1px, `border-accent`/`border-strong`, under view titles and around
  framed panels. `linear-gradient(90deg, var(--color-border-strong), transparent)` fade allowed.
- **Corner ticks** — 14px L-brackets in `border-strong` on **the one primary panel per view**
  (the approval card, the live activity card, the trace summary). Not on every panel: a frame that
  is everywhere frames nothing.
- **Scanline texture** — `repeating-linear-gradient(0deg, rgba(240,180,41,.013) 0 1px,
  transparent 1px 3px)` on `--color-canvas` **only**, never behind a panel's text. ≤2% opacity,
  imperceptible as a pattern, present as tooth.
- **Gold glow — on the armed/active element only:** `--glow-armed: 0 0 0 1px
  rgba(240,180,41,.55), 0 0 18px rgba(240,180,41,.28)`. Exactly two legal carriers: an **armed**
  decision control (spec §6.7 Armed state) and the **live** WorkIndicator pulse (§6 `work-pulse`,
  re-coloured gold, same 1100ms timing, same reduced-motion kill-switch). Nothing at rest glows.
- **Focus ring** — 2px solid `accent` outline, 2px offset, + `--focus: 0 0 0 4px
  rgba(240,180,41,.25)`. Ring contrast ≥8.6:1 against the lightest surface (needs 3:1).

Forbidden, in writing: parallax, animated backgrounds, glassmorphism/backdrop blur, neon
multi-hue gradients, decorative motion, any texture behind body text. The test for every
atmospheric: *would it annoy at 8am on a Tuesday?*

## A.5 Typography — futurism by geometry, not costume

| Token | Face (Google Fonts) | Weights | Use |
|---|---|---|---|
| `--font-display` | **Space Grotesk** | 500 / 700 | Wordmark, view titles (H1), panel headings, stat figures. Squared terminals and technical counters carry the instrument feel at reading sizes — which Orbitron cannot: it is a costume face with a weak lowercase, and at micro sizes it costs exactly the legibility this rework is buying. Orbitron is retired from V2 surfaces |
| `--font-body` | **Inter** | 400 / 500 / 600 / 700 | All UI text, table cells, prose. Replaces the all-mono body: a proportional body at 13–14px buys ~20% more characters per line — the owner asked for *"all the info displayed properly"*, and density is a typography decision before it is a layout one. Share Tech Mono (one weight, no bold) is retired from V2 surfaces |
| `--font-mono` | **JetBrains Mono** | 400 / 600 / 700 | Everything that is *data*: ids, hashes, params, code, timestamps, countdowns, trace offsets, JSON. Continuity with M1; the mono is what makes machine-text visibly machine-text next to an Inter body |

Scale (rem-based, root 16px — rem rule from §2 unchanged):

| Style | Font | Size / line | Weight | Tracking | Use |
|---|---|---|---|---|---|
| Display | display | 22px / 1.2 | 700 | .08em, uppercase | View H1, wordmark |
| H2 / panel | display | 12px / 1.4 | 700 | .18em, uppercase | Section + panel headings, `text-secondary` |
| Body | body | 14px / 1.55 | 400 | normal | Default UI text |
| Table cell | body | 13px / 1.5 | 400 | normal | Dense list rows |
| Small / meta | body | 12px / 1.5 | 400 | .01em | Captions, helper lines |
| Micro / label | body | 10px / 1.4 | 600 | .12em, uppercase | Column headers, pills, provenance labels |
| Data | mono | 12–13px / 1.5 | 400 | normal | Ids, params, offsets, countdowns |
| Stat figure | display | 20px / 1.2 | 700 | .02em | Summary-rail numbers |

**Tabular figures everywhere data aligns** (kept from round 1, now load-bearing for Inter, which is
proportional by default): `font-variant-numeric: tabular-nums` on `body`, and any ticking countdown
must never reflow its row.

## A.6 Density — "all the info displayed properly" (normative)

The owner's verdict says round 1 felt like it hid things. These rules fix that:

1. **Summary rail** at the top of every list view: 3–5 figures visible at rest (Approvals: pending /
   oldest wait / next expiry / decided-7d. Activity: running / parked / failed-today. Tasks, Audit:
   equivalents). One figure per view may be gold (A.2 rule 1).
2. **Timestamps show relative *and* absolute at rest** — `18 min ago · 09:41:06` — never absolute
   behind hover only. Round 1's hover-`<time>` pattern is dead.
3. **Exception rows arrive expanded** (audit traces: non-`allow` decisions, `ok:false` results,
   non-`ok` outcomes — unchanged from Decision 8) and collapsed rows still surface their contracted
   key figures inline (offset, duration, token counts) so a closed trace is scannable.
4. **Nothing meant to be read hides behind hover.** Hover may *add* affordance (row tint), never
   *reveal* content. Keyboard and touch see everything a mouse sees.
5. Table density: row padding `py-2.5 px-4` (44px effective target preserved via padding), header
   `py-2 px-4` micro-label style, section gap `gap-6`, ops content `max-w-6xl`, chat column
   `max-w-3xl` inside it, nav rail 88/232/64px + 5-item bottom bar <768px — carried from round 1.

## A.7 Contrast — computed pairs (WCAG relative-luminance method)

| Pair | Ratio | Requirement | Result |
|---|---|---|---|
| `text-primary` #F5EFE3 on canvas #000000 | 18.3:1 | 4.5:1 | Pass AAA |
| `text-primary` on `surface-high` #282318 (hardest ground) | 13.7:1 | 4.5:1 | Pass AAA |
| `text-secondary` #DECFA8 on canvas | 13.6:1 | 4.5:1 | Pass AAA |
| `text-muted` #A89A7E on canvas / surface / raised / high | 7.6 / 6.9 / 6.3 / 5.7:1 | 4.5:1 | Pass on all four grounds |
| `accent` (gold) #F0B429 on canvas / surface / high | 11.6 / 10.5 / 8.6:1 | 4.5:1 (text) / 3:1 (ring) | Pass everywhere, both uses |
| `gold-deep` #C9971F on canvas / surface | 7.9 / 7.2:1 | 4.5:1 | Pass |
| `accent-on` ink #161006 on gold fill #F0B429 | 10.4:1 | 4.5:1 | Pass AAA |
| ink on `accent-hover` #FFCB57 | 12.5:1 | 4.5:1 | Pass AAA |
| ink on `status-pending` fill #FF9E45 (rail badge) | 9.2:1 | 4.5:1 | Pass |
| `status-pending` #FF9E45 on canvas / surface | 10.2 / 9.3:1 | 4.5:1 | Pass |
| `status-approved` #6EA8FE on canvas / surface | 8.7 / 7.9:1 | 4.5:1 | Pass |
| `success` #43C878 on canvas / surface | 9.8 / 8.8:1 | 4.5:1 | Pass |
| `danger` #FF6B5E on canvas / surface / raised | 7.5 / 6.8 / 6.3:1 | 4.5:1 | Pass |
| ink on `danger-strong` fill #E5484D | 4.8:1 | 4.5:1 | Pass (white on it is 3.9:1 — **fails**, which is why the on-fill ink is dark, not white) |
| focus ring gold vs `surface-high` | 8.6:1 | 3:1 | Pass |
| *(rejected)* dark ochre #B45309 as text on canvas | 4.2:1 | 4.5:1 | **Fails** — why the ochre is #C9971F, not the darker "antique" value the mood wanted |
| *(rejected)* #FFD700 web-gold as the accent | 15.0:1 | — | Passes contrast, rejected on discipline: neon-yellow reads as costume, not instrument, and collides with any amber signal |
| *(rejected)* #FFFFFF as text-primary | 21:1 | — | Passes, rejected for halation glare on true black in a dark room — warm off-white keeps AAA without the shimmer |

Rule of thumb, restated for the new grounds: a solid colour needs relative luminance ≥ **0.20** to
clear 4.5:1 body-text contrast on these blacks. Compute before shipping; never eyeball.

## A.8 Tailwind config (paste into `tailwind.config.ts` → `theme.extend`)

```ts
colors: {
  canvas: "#000000",
  surface: { DEFAULT: "#12100B", raised: "#1C1913", high: "#282318" },
  border: { DEFAULT: "#2B2416", accent: "rgba(240,180,41,.20)", strong: "rgba(240,180,41,.45)" },
  accent: { DEFAULT: "#F0B429", hover: "#FFCB57", active: "#D69C1E", on: "#161006" },
  gold: { deep: "#C9971F" },
  text: { primary: "#F5EFE3", secondary: "#DECFA8", muted: "#A89A7E", disabled: "#5D5442" },
  status: {
    pending: "#FF9E45", approved: "#6EA8FE", consumed: "#43C878",
    refused: "#FF6B5E", expired: "#A89A7E",
  },
  success: "#43C878",
  warning: "#FF9E45",
  danger: { DEFAULT: "#FF6B5E", strong: "#E5484D" },
},
fontFamily: {
  display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],   // Space Grotesk
  body: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],         // Inter
  mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"], // JetBrains Mono
},
boxShadow: {
  "glow-armed": "0 0 0 1px rgba(240,180,41,.55), 0 0 18px rgba(240,180,41,.28)",
  "glow-focus": "0 0 0 4px rgba(240,180,41,.25)",
},
keyframes: {
  "work-pulse": {
    "0%, 100%": { boxShadow: "0 0 0 1px rgba(240,180,41,.45), 0 0 16px rgba(240,180,41,.22)" },
    "50%":      { boxShadow: "0 0 0 1px rgba(240,180,41,.60), 0 0 30px rgba(240,180,41,.34)" },
  },
},
animation: { "work-pulse": "work-pulse 1100ms cubic-bezier(0.4,0,0.2,1) infinite" },
```

`color-scheme: dark` on `:root`. **No `prefers-color-scheme` media query anywhere** — the theme is
committed, every colour painted explicitly, body background explicit. There is no light map to
drift out of sync. The `prefers-reduced-motion` kill-switch from §7 stays global and unchanged.

