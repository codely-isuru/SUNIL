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
