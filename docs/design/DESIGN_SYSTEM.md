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

# AMENDMENT A — V2 "Obsidian & Gold" instrument theme (rounds 2–3, owner-directed)

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

**Re-tuned in place: 2026-09-11 (round 3)** after the owner reviewed the round-2 mockups:
*"the contrast are bit high on these designs its hard to keep on the eye for a long time. make it
so it got a cool effects. remove yellow keep black and gold colors."* Three rulings, applied
throughout this amendment:
1. **A comfort ceiling joins the AA floor (§A.7).** Round 2's body text ran to 18.3:1 — clinical
   and fatiguing over hours. Body text now lands **9–13:1** on every ground (never below AA 4.5:1
   anywhere), muted text is dimmer, hairlines are quieter, and the canvas lifts off pure `#000000`
   to a warm near-black — pure black maximises the perceived harshness of any text on it.
2. **The gold is de-yellowed.** `#F0B429` read yellow; the ramp moves to antique/metallic gold —
   accent `#C9A227`, hover toward pale champagne (not lemon), pressed toward bronze. Pending
   moves from yellow-orange `#FF9E45` to **copper** `#D98E4A` so nothing on screen reads yellow,
   with a named distinction rule from the brand gold (§A.3).
3. **The atmospherics budget (§A.4) is deliberately expanded** — panel sheens, a metallic gradient
   on gold fills, a key-figure glow, a slowed live pulse and one shimmer sweep — every animation
   reduced-motion-safe, none on a reading surface.
Structure, token names, type system (§A.5), density rules (§A.6) and every interaction/security
decision are unchanged from round 2.

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
| `--color-canvas` | `#0B0906` | .0028 | The void — warm **near**-black, lifted off pure `#000000` (round 3). Still reads black; the lift removes the halation harshness true black gives every glyph on it. The only surface that may carry the scanline texture (A.4) |
| `--color-surface` | `#16120C` | .0063 | Panels, cards, tables, rail, topbar — warm charcoal, one step up |
| `--color-surface-raised` | `#201A11` | .0109 | Row hover, untrusted blocks, expanded trace rows, table headers |
| `--color-surface-high` | `#2B2315` | .0177 | Inputs, code blocks, the highest layer (confirm steps, sheets) |
| `--color-border` | `#282013` | .0175 | Structural 1px dividers (non-text; ~1.2:1 vs surface — deliberately quiet, quieter than round 2) |
| `--color-border-accent` | `rgba(201,162,39,.16)` | — | Decorative gold hairline on framed panels (was .20 — hairlines quieter for long sessions). Non-text only |
| `--color-border-strong` | `rgba(201,162,39,.38)` | — | Hover/focus-adjacent hairline upgrade, corner ticks (was .45). Non-text only |

**The elevation rule (replaces §5 for V2 surfaces):** depth = one surface step up + a 1px border.
There is **no drop-shadow scale and no glow-as-elevation** in this theme. Glow exists, but it is a
*state* (A.4), never a height. A panel that needs to read "above" another gets a lighter ground,
which is how a physical instrument panel does it.

## A.2 The gold ramp — and the discipline that keeps it precious

| Token | Hex | Role |
|---|---|---|
| `--color-accent` | `#C9A227` | **The gold — antique/metallic (hue ≈46°), not yellow.** Interactive elements: links, primary button fill, active nav edge, focus ring, the single key figure per view. 8.2:1 on canvas — reads as metal, not lemon |
| `--color-accent-hover` | `#DBBE7F` | Hover lift — **pale champagne**, the "light catches the metal" direction, deliberately not a brighter yellow (11.1:1) |
| `--color-accent-active` | `#A6801F` | Pressed — **bronze**, darker than rest, the "metal compresses" direction (5.4:1) |
| `--color-accent-on` | `#14100A` | Ink — text/icons on any gold or status fill (7.8:1 on the gold, 10.5:1 on champagne hover, 5.2:1 on pressed bronze — AA at every stop of the metallic sheen too) |
| `--color-gold-deep` | `#B08A2A` | Dark antique gold: secondary emphasis — decided-count figures, section accents, "warm" metadata that must not compete with interactive gold (6.2:1 on canvas) |
| `--color-text-primary` | `#CEC5B4` | Body text — warm bone, tuned INTO the 9–13:1 comfort band: 11.6:1 on canvas, 9.1:1 on the lightest ground. Round 2's `#F5EFE3` (18.3:1) is retired as sustained-reading text — the owner's "hard to keep on the eye" verdict is a report that AAA-with-room-to-spare was over-bright for hours-long use |
| `--color-text-secondary` | `#C4B48D` | Headings, emphasis, panel titles — champagne-tinted (9.7:1 canvas) |
| `--color-text-muted` | `#9A8D71` | Desaturated sand: meta text, timestamps, labels (6.1:1 canvas / 4.7:1 on the lightest surface — dimmer than round 2, still AA everywhere it can legally sit) |
| `--color-text-disabled` | `#59503C` | Disabled labels (non-text requirement; visibly dimmer, clearly not interactive) |

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
chrome. V2 statuses are therefore their own hues, each AA on every ground they sit on. Round 3
re-tuned every status: pending moved off yellow-orange entirely (owner: *"remove yellow"*), and the
blue/green/red were pulled down into the comfort range:

| Token | Hex | On canvas | Meaning | Why this hue |
|---|---|---|---|---|
| `--status-pending` | `#D98E4A` | 7.5:1 | Waiting on the owner. Also `--color-warning` (stale, banners, parked) | **Copper** (hue ≈28°, visible red content) — round 2's `#FF9E45` still read yellow-orange. **Distinction rule from the brand gold (≈46°, no red): gold is the system's voice, copper is a situation's state — and status colour only ever appears in the pill/edge/badge grammar with icon + label, where gold never wears a pill** |
| `--status-approved` | `#5E96E0` | 6.5:1 | Decided, not yet executed | Signal blue — "cleared to run". Deliberately still not green: approved ≠ done |
| `--status-consumed` | `#3FAE6C` | 7.1:1 | Executed, single use spent. Also `--color-success` | Green stays reserved for *actually happened* |
| `--status-refused` | `#E8685C` | 6.2:1 | Owner said no. Also `--color-danger` | — |
| `--status-expired` | `#9A8D71` | 6.1:1 | Timed out, never ran (= `text-muted`) | Neutral on purpose: an expiry is not an error the owner caused |
| `--color-danger-strong` | `#E5484D` | fill | Danger button fill, paired with `--color-accent-on` ink (4.8:1 — unchanged: dimming this fill would break the on-fill ink's AA) | — |

Task `in_progress`/RUNNING maps to **gold** deliberately — it is the one status allowed to share
the brand hue, because "SUNIL is alive right now" *is* the live/active state the glow budget (A.4)
exists for. Every status remains icon + uppercase text + colour + edge pattern (spec §12.3);
greyscale-printed rows stay classifiable.

Untrusted-containment and table roles carry over from round 1 unchanged in role, revalued:
`--color-untrusted-bg` = `surface-raised`, `--color-untrusted-bar` = `text-muted` (sand),
`--color-row-hover` = `surface-raised`, `--color-redacted` = `text-disabled`. The containment is
carried by the left bar + provenance label, not by a novel colour — unchanged from Decision 3.

## A.4 Light is a state; texture is a whisper (the atmospherics budget — EXPANDED in round 3)

The owner's round-3 verdict asked for *"cool effects"*. The budget below is that request granted
deliberately: each item is CSS-only, carries meaning or material (never mere decoration), respects
`prefers-reduced-motion`, and **no animation ever sits on a reading surface** (untrusted blocks,
chat message bodies, param tables stay flat and still).

Permitted, and only these:
- **Hairline gold rules** — 1px, `border-accent`/`border-strong`, under view titles and around
  framed panels. `linear-gradient(90deg, var(--color-border-strong), transparent)` fade allowed.
- **Corner ticks** — 14px L-brackets in `border-strong` on **the one primary panel per view**
  (the approval card, the live activity card, the trace summary). Not on every panel: a frame that
  is everywhere frames nothing.
- **Scanline texture** — `repeating-linear-gradient(0deg, rgba(201,162,39,.012) 0 1px,
  transparent 1px 3px)` on `--color-canvas` **only**, never behind a panel's text. ≤1.5% opacity,
  imperceptible as a pattern, present as tooth.
- **Panel sheen (new, round 3)** — `--sheen-panel: linear-gradient(180deg, rgba(201,162,39,.03),
  rgba(201,162,39,0) 46%)` as a `background-image` on panels, cards and tables: a barely-there
  top light that makes surfaces read as brushed material instead of flat fills. ≤3% gold alpha —
  its worst-case effect on any text contrast is below one decimal place. **Never** on the
  untrusted-text containers or chat message bodies: reading surfaces stay flat.
- **Metallic sheen on gold fills (new, round 3)** — `--sheen-metal: linear-gradient(180deg,
  rgba(255,255,255,.14), rgba(255,255,255,0) 45%, rgba(0,0,0,.12))` overlaid on the primary
  button's gold: light top edge, weighted base — gold as machined metal, no image assets. The
  on-fill ink stays ≥4.5:1 at the brightest stop (§A.7).
- **Key-figure glow (new, round 3)** — `text-shadow: 0 0 14px rgba(201,162,39,.32)` on **the one
  gold figure per view** (§A.6 rule 1). A faint halo on the number the view exists for; not on any
  other stat.
- **Gold glow — armed/live states:** `--glow-armed: 0 0 0 1px rgba(201,162,39,.55), 0 0 18px
  rgba(201,162,39,.30)`. Two legal carriers, unchanged: an **armed** decision control (spec §6.7)
  and the **live** WorkIndicator pulse. **The pulse slows from 1100ms to 2600ms (round 3):** a
  working system breathes calmly; 1100ms read as urgency. Same reduced-motion kill-switch — the
  static border fallback keeps the state legible without motion. Nothing at rest glows.
- **Shimmer sweep (new, round 3)** — a single 45%-wide, 20%-white diagonal highlight sweeping the
  **armed confirm button only** (`@keyframes shimmer`, 2600ms, same easing family). It marks the
  one control whose next press is irreversible as *live, right now*. Removed entirely under
  `prefers-reduced-motion` (`content: none`), where the armed glow border still carries the state.
- **Focus ring** — 2px solid `accent` outline, 2px offset, + `--focus: 0 0 0 4px
  rgba(201,162,39,.22)`. Ring contrast 6.4:1 against the lightest surface (needs 3:1).

Forbidden, in writing: parallax, animated backgrounds, glassmorphism/backdrop blur, neon
multi-hue gradients, decorative motion, any texture or animation behind body text. The test for
every atmospheric: *would it annoy at 8am on a Tuesday?*

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

## A.7 Contrast — computed pairs (WCAG relative-luminance method), with the comfort ceiling

**The two-sided rule (round 3, normative).** The AA floor is unchanged: **≥4.5:1 for all text,
everywhere, no exceptions.** Round 3 adds a **comfort ceiling**: any text read at length (body,
table cells, prose, headings) targets **9–13:1** against its actual ground and must not exceed
**13.5:1**. Very high contrast is not "extra accessible" — on a dark theme used for hours it is
glare (the owner's verdict: *"hard to keep on the eye for a long time"*). Short-exposure elements
(a hover state, a key figure, an armed label) may sit near the top of the band; nothing on a V2
surface renders text above 11.6:1. Anyone adding a token later must satisfy **both** bounds.

Grounds: canvas `#0B0906` L≈.0028 · surface `#16120C` L≈.0063 · raised `#201A11` L≈.0109 ·
high `#2B2315` L≈.0177.

| Pair | Ratio | Requirement | Result |
|---|---|---|---|
| `text-primary` #CEC5B4 on canvas / surface / raised / high | 11.6 / 10.9 / 10.1 / 9.1:1 | 4.5:1 floor · 9–13:1 band | Pass — in the comfort band on all four grounds |
| `text-secondary` #C4B48D on canvas / high | 9.7 / 7.6:1 | 4.5:1 | Pass |
| `text-muted` #9A8D71 on canvas / surface / raised / high | 6.1 / 5.7 / 5.3 / 4.7:1 | 4.5:1 | Pass on all four grounds (high is the binding case — this is why muted is not dimmer still) |
| `accent` (gold) #C9A227 on canvas / surface / high | 8.2 / 7.7 / 6.4:1 | 4.5:1 (text) / 3:1 (ring) | Pass everywhere, both uses |
| `accent-hover` #DBBE7F on canvas | 11.1:1 | 4.5:1 | Pass (momentary state — top of band is fine) |
| `accent-active` #A6801F (bronze) on canvas | 5.4:1 | 4.5:1 | Pass |
| `gold-deep` #B08A2A on canvas / surface | 6.2 / 5.8:1 | 4.5:1 | Pass |
| `accent-on` ink #14100A on gold fill #C9A227 | 7.8:1 | 4.5:1 | Pass |
| ink on `accent-hover` #DBBE7F / on `accent-active` #A6801F | 10.5 / 5.2:1 | 4.5:1 | Pass — the metallic sheen's brightest and darkest stops both hold AA for the button label |
| ink on `status-pending` fill #D98E4A (rail badge) | 8.1:1 | 4.5:1 | Pass |
| `status-pending` #D98E4A (copper) on canvas / high | 7.5 / 5.9:1 | 4.5:1 | Pass |
| `status-approved` #5E96E0 on canvas / high | 6.5 / 5.1:1 | 4.5:1 | Pass |
| `success` #3FAE6C on canvas / high | 7.1 / 5.5:1 | 4.5:1 | Pass |
| `danger` #E8685C on canvas / surface / raised / high | 6.2 / 5.8 / 5.4 / 4.9:1 | 4.5:1 | Pass |
| ink on `danger-strong` fill #E5484D | 4.8:1 | 4.5:1 | Pass (fill kept from round 2 — dimming it would break this pair) |
| focus ring gold #C9A227 vs `surface-high` | 6.4:1 | 3:1 | Pass |
| *(retired)* round 2's `text-primary` #F5EFE3 on canvas | 18.3:1 | ≤13.5:1 ceiling | **Above the ceiling** — the exact value the owner reported as eye strain; retired from sustained-reading use |
| *(rejected)* #B8912F as the accent | 6.8:1 canvas / 5.3:1 high | 4.5:1 | Passes, rejected on ramp mechanics: it sits only ~0.9 above the pressed bronze #A6801F (5.4:1), so accent / gold-deep / pressed collapse into one brightness and the pressed state stops reading — #C9A227 keeps the same antique hue with a legible three-step ramp |
| *(rejected)* pure #000000 canvas | — | — | Kept round 2's mood but maximises perceived harshness (halation) of every glyph; the #0B0906 lift is invisible as "grey" and measurably gentler |
| *(rejected)* #8A7D63 as text-muted | 3.8:1 on surface-high | 4.5:1 | **Fails** on the lightest ground — why muted is #9A8D71 and not one step dimmer |

Rule of thumb, restated for the new grounds: a solid colour needs relative luminance ≥ **0.255**
to clear 4.5:1 on `surface-high` (the binding ground), and should stay ≤ **0.63** to respect the
comfort ceiling on canvas. Compute before shipping; never eyeball.

## A.8 Tailwind config (paste into `tailwind.config.ts` → `theme.extend`)

```ts
colors: {
  canvas: "#0B0906",
  surface: { DEFAULT: "#16120C", raised: "#201A11", high: "#2B2315" },
  border: { DEFAULT: "#282013", accent: "rgba(201,162,39,.16)", strong: "rgba(201,162,39,.38)" },
  accent: { DEFAULT: "#C9A227", hover: "#DBBE7F", active: "#A6801F", on: "#14100A" },
  gold: { deep: "#B08A2A" },
  text: { primary: "#CEC5B4", secondary: "#C4B48D", muted: "#9A8D71", disabled: "#59503C" },
  status: {
    pending: "#D98E4A", approved: "#5E96E0", consumed: "#3FAE6C",
    refused: "#E8685C", expired: "#9A8D71",
  },
  success: "#3FAE6C",
  warning: "#D98E4A",
  danger: { DEFAULT: "#E8685C", strong: "#E5484D" },
},
fontFamily: {
  display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],   // Space Grotesk
  body: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],         // Inter
  mono: ["var(--font-mono)", "ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"], // JetBrains Mono
},
backgroundImage: {
  // atmosphere (§A.4): panel top-light + metallic overlay for gold fills
  "sheen-panel": "linear-gradient(180deg, rgba(201,162,39,.03), rgba(201,162,39,0) 46%)",
  "sheen-metal": "linear-gradient(180deg, rgba(255,255,255,.14), rgba(255,255,255,0) 45%, rgba(0,0,0,.12))",
},
boxShadow: {
  "glow-armed": "0 0 0 1px rgba(201,162,39,.55), 0 0 18px rgba(201,162,39,.30)",
  "glow-focus": "0 0 0 4px rgba(201,162,39,.22)",
},
keyframes: {
  "work-pulse": {
    "0%, 100%": { boxShadow: "0 0 0 1px rgba(201,162,39,.42), 0 0 14px rgba(201,162,39,.20)" },
    "50%":      { boxShadow: "0 0 0 1px rgba(201,162,39,.58), 0 0 26px rgba(201,162,39,.32)" },
  },
  shimmer: { "0%": { left: "-60%" }, "60%, 100%": { left: "115%" } },
},
animation: {
  // round 3: the live pulse breathes at 2600ms (1100ms read as urgency, not liveness)
  "work-pulse": "work-pulse 2600ms cubic-bezier(0.4,0,0.2,1) infinite",
  shimmer: "shimmer 2600ms cubic-bezier(0.4,0,0.2,1) infinite", // armed confirm button only (§A.4)
},
```

`color-scheme: dark` on `:root`. **No `prefers-color-scheme` media query anywhere** — the theme is
committed, every colour painted explicitly, body background explicit. There is no light map to
drift out of sync. The `prefers-reduced-motion` kill-switch from §7 stays global and unchanged.

