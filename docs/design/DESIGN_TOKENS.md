# SUNIL — Design Tokens (Phase 1)

_Owner: UI/UX Designer (Minions delivery team)_
_Status: **Developer-ready.** Blocks BL-502, BL-503, BL-504, BL-505._
_Covers: FR-100, FR-103, NFR-016, R-10, D-02_
_Primary source: `prototype/sunil-command-centre.html` (read-only design reference, per A-15)_
_Binding constraints: `SUNIL_ARCHITECTURE.md` §3_

> **How to read this document.** Every token below is either **extracted** — traced to a literal
> value in the prototype, quoted verbatim — or **introduced**, with a written justification. No
> token is invented silently. §5 is a full WCAG 2.1 contrast audit with **computed** ratios (not
> estimates); §6 records every place where the prototype's value had to change to pass, showing
> original → corrected so the human can judge the trade-off.
>
> **The three-layer rule is not decoration.** Component tokens reference semantic tokens.
> Semantic tokens reference primitives. Components never reference primitives, and nothing in
> `apps/web` references a raw hex value. This is what makes §8 (light theme) a re-binding
> exercise rather than a rewrite, and it is enforceable at review (FR-100: "no brand colour is
> hard-coded as a literal outside the token definitions").

---

## 1. Package placement and consumption

| Item | Path | Notes |
|---|---|---|
| Token stylesheet | `packages/ui/src/tokens/tokens.css` | The single source of the CSS custom properties in §2–§4 |
| Typed exports | `packages/ui/src/tokens/tokens.ts` | `as const` objects mirroring the CSS, for canvas/JS consumers |
| Theme attachment | `:root, [data-theme="dark"]` | Dark is the only Phase 1 theme (FR-103) |
| Global import | `apps/web/app/layout.tsx` | Imported **before** any component CSS so no unstyled/light flash occurs (FR-103) |

`tokens.ts` exists because `<SunilPresence />` draws to a canvas and cannot read CSS variables
from a stylesheet at paint time without a `getComputedStyle` call. The rule for that component is
in `SUNIL_PRESENCE_SPEC.md` §7: it reads the CSS variables once per mount/theme-change and caches
them — `tokens.ts` is the typed fallback and the test fixture, not a second source of truth.

**Naming convention:** `--sunil-<layer>-<role>-<variant>`. Numeric suffixes on primitives are
lightness steps (higher = lighter). Numeric suffixes on spacing **are the pixel value**, so
`--sunil-space-16` is `16px` — there is nothing to memorise.

---

## 2. Layer 1 — Primitives

Primitives are raw values with no meaning attached. **Nothing outside the semantic layer may
reference these.**

### 2.1 Colour — Cyan ramp (the brand hue)

The prototype uses four cyans and one sky. All five are Tailwind palette values, which tells us
the prototype's author was picking from `cyan-*` / `sky-*`; the ramp below completes that family
so future needs do not require a fresh eyedropper.

| Token | Value | Origin |
|---|---|---|
| `--sunil-cyan-100` | `#CFFAFE` | **Introduced** — completes the ramp; needed for a high-contrast pressed/active accent |
| `--sunil-cyan-200` | `#A5F3FC` | **Extracted** — `.greeting{color:#a5f3fc}` and the canvas orbital marker `ctx.fillStyle='#a5f3fc'` |
| `--sunil-cyan-300` | `#67E8F9` | **Extracted** — `.scanlines` gradient and the sphere point fill `rgba(103,232,249,α)` |
| `--sunil-cyan-400` | `#22D3EE` | **Extracted** — `--cyan:#22d3ee`. The brand colour. Locked by `SUNIL_ARCHITECTURE.md` §3 |
| `--sunil-cyan-500` | `#06B6D4` | **Introduced** — ramp completion |
| `--sunil-cyan-600` | `#0891B2` | **Introduced** — ramp completion |
| `--sunil-cyan-700` | `#0E7490` | **Introduced** — ramp completion; the light-theme text candidate (§8) |
| `--sunil-cyan-800` | `#155E75` | **Introduced** — ramp completion |
| `--sunil-cyan-900` | `#164E63` | **Introduced** — ramp completion |
| `--sunil-cyan-a08` | `rgba(34, 211, 238, 0.08)` | **Extracted** — `#briefBtn{background:rgba(34,211,238,.08)}` |
| `--sunil-cyan-a12` | `rgba(34, 211, 238, 0.12)` | **Extracted** — `.sysrow{border-bottom:1px dashed rgba(34,211,238,.12)}` |
| `--sunil-cyan-a18` | `rgba(34, 211, 238, 0.18)` | **Extracted** — `--cyan-faint:rgba(34,211,238,.18)` |
| `--sunil-cyan-a20` | `rgba(34, 211, 238, 0.20)` | **Extracted** — `#briefBtn:hover{background:rgba(34,211,238,.2)}` |
| `--sunil-cyan-a28` | `rgba(34, 211, 238, 0.28)` | **Extracted** — `#briefBtn.speaking{background:rgba(34,211,238,.28)}` |
| `--sunil-cyan-a55` | `rgba(34, 211, 238, 0.55)` | **Extracted** — `--cyan-dim:rgba(34,211,238,.55)`. **Retained as a primitive for glow/stroke use only. Forbidden as a text colour — see §5 and §6.1.** |

### 2.2 Colour — Sky (heading tint)

| Token | Value | Origin |
|---|---|---|
| `--sunil-sky-300` | `#7DD3FC` | **Extracted** — `.panel h2{color:#7dd3fc}` |

### 2.3 Colour — Ice ramp (cyan-tinted neutrals)

**Introduced in full.** Justification: the prototype has exactly two text colours — full cyan and
55%-alpha cyan — and the second of those fails AA (§5). A dark HUD cannot express text hierarchy
by dimming, because dimming *is* the failure mode. The ice ramp gives hierarchy through
**desaturation at held luminance**, which is the only move available on a `#030712` background,
and it keeps the cool cast so nothing reads as "grey web app". Steps are spaced ≈1.15× in
contrast ratio so adjacent steps are visibly distinct.

| Token | Value | Ratio on `--sunil-bg` | Ratio on panel |
|---|---|---|---|
| `--sunil-ice-50` | `#F2FBFD` | 19.17 | 18.44 |
| `--sunil-ice-100` | `#E3F5FA` | 17.94 | 17.25 |
| `--sunil-ice-200` | `#D3ECF4` | 16.37 | 15.74 |
| `--sunil-ice-300` | `#C0E0EB` | 14.48 | 13.93 |
| `--sunil-ice-400` | `#ADD3E0` | 12.63 | 12.14 |
| `--sunil-ice-500` | `#9AC5D4` | 10.84 | 10.43 |
| `--sunil-ice-600` | `#88B7C8` | 9.26 | 8.90 |
| `--sunil-ice-700` | `#76A8BB` | 7.76 | 7.46 |
| `--sunil-ice-800` | `#6499AE` | 6.43 | 6.19 |
| `--sunil-ice-900` | `#456A7C` | 3.46 | 3.32 |

> `--sunil-ice-900` is below 4.5:1 and is **non-text only** (rules, chip edges). It is in the ramp
> for completeness; a lint rule should reject it as a `color` value.

### 2.4 Colour — Depth (surfaces)

| Token | Value | Origin |
|---|---|---|
| `--sunil-void-900` | `#030712` | **Extracted** — `--bg:#030712`. Locked by architecture |
| `--sunil-void-800` | `rgba(7, 16, 32, 0.72)` | **Extracted** — `--panel:rgba(7,16,32,.72)`. Locked by architecture |
| `--sunil-void-800-solid` | `#060D1C` | **Introduced** — the exact composite of `--sunil-void-800` over `--sunil-void-900`. Required so contrast can be computed deterministically and so panels that sit over the presence canvas can opt out of translucency (§5.2) |
| `--sunil-void-700` | `#0B172A` | **Introduced** — a raised surface for menus, popovers, table header rows and the mobile nav drawer. The prototype has exactly one surface level; a shell with a drawer and modals needs two |
| `--sunil-void-600` | `#122238` | **Introduced** — input field fill; sits above the raised surface so a field reads as an inset control |
| `--sunil-scrim` | `rgba(3, 7, 18, 0.82)` | **Introduced** — the mandatory backdrop for any text placed over the presence canvas (§5.2) and for modal overlays |

### 2.5 Colour — Status

| Token | Value | Origin |
|---|---|---|
| `--sunil-emerald-400` | `#34D399` | **Extracted** — `--ok:#34d399`. Locked by architecture |
| `--sunil-amber-400` | `#FBBF24` | **Extracted** — `--amber:#fbbf24`. Locked by architecture |
| `--sunil-rose-400` | `#F87171` | **Extracted** — `.delta.down{color:#f87171}` |
| `--sunil-rose-300` | `#FCA5A5` | **Introduced** — a lighter rose for error text on the raised surface, where `--sunil-rose-400` at small sizes is the tightest passing value in the set |
| `--sunil-slate-500` | `#64748B` | **Introduced** — replaces the prototype's `#475569` for the "offline" lamp, which fails 3:1 (§6.2) |
| `--sunil-slate-600` | `#475569` | **Extracted** — `.lamp.off{background:#475569}`. **Retained as a primitive for non-informational fills only; forbidden for status indication** |

### 2.6 Typography primitives

| Token | Value | Origin |
|---|---|---|
| `--sunil-font-display` | `'Orbitron', 'Orbitron Fallback', 'Trebuchet MS', ui-sans-serif, system-ui, sans-serif` | **Extracted** — `font-family:'Orbitron',sans-serif`; fallback chain **introduced** (§7) |
| `--sunil-font-mono` | `'Share Tech Mono', 'Share Tech Mono Fallback', ui-monospace, 'Cascadia Mono', Consolas, 'Courier New', monospace` | **Extracted** — `font-family:'Share Tech Mono',ui-monospace,monospace`; chain extended for Windows (§7) |
| `--sunil-weight-regular` | `400` | **Extracted** — Orbitron 400 loaded |
| `--sunil-weight-semibold` | `600` | **Extracted** — `.clock`, `.panel h2`, `.stat .val`, `#briefBtn` |
| `--sunil-weight-bold` | `800` | **Extracted** — `h1{font-weight:800}` |

Sizes, line heights and tracking are semantic (§3.2) because the prototype's raw sizes include two
values (10px, 11px) that are being changed — see §6.4.

### 2.7 Space primitives

Base grid **4px**. The prototype is on a 2px grid with three off-grid values; those are recorded
in §6.5.

```
--sunil-space-0:  0;      --sunil-space-2:  2px;   --sunil-space-4:  4px;
--sunil-space-6:  6px;    --sunil-space-8:  8px;   --sunil-space-10: 10px;
--sunil-space-12: 12px;   --sunil-space-14: 14px;  --sunil-space-16: 16px;
--sunil-space-20: 20px;   --sunil-space-24: 24px;  --sunil-space-28: 28px;
--sunil-space-32: 32px;   --sunil-space-40: 40px;  --sunil-space-48: 48px;
--sunil-space-64: 64px;   --sunil-space-80: 80px;  --sunil-space-96: 96px;
```

Origins: `6px`/`8px`/`10px` (row padding, lamp size), `12px`/`14px`/`16px` (`.panel{padding:14px 16px}`,
`.stat{padding:12px 22px}`), `16px`/`18px` (`.left-col{gap:16px}`, `.hud{gap:18px}` → snapped to 16),
`22px`/`26px` (`.stat` horizontal padding, `.hud{padding:26px}` → snapped to 24). Everything ≥28px is
**introduced** for the shell, which has layout needs the single-screen prototype never had.

### 2.8 Radius, border, glow, z-index, motion primitives

```
/* radius — prototype uses 6px universally and 50% for lamps */
--sunil-radius-0:    0;
--sunil-radius-2:    2px;   /* introduced: chips, badges */
--sunil-radius-4:    4px;   /* introduced: inputs, small buttons */
--sunil-radius-6:    6px;   /* EXTRACTED: .panel, .stat, #briefBtn all border-radius:6px */
--sunil-radius-10:   10px;  /* introduced: modals, drawer */
--sunil-radius-full: 9999px;/* EXTRACTED (as 50%): .lamp{border-radius:50%} */

/* border width */
--sunil-border-1: 1px;      /* EXTRACTED: .panel{border:1px solid …} */
--sunil-border-2: 2px;      /* EXTRACTED: .panel::before{height:2px} accent bar; also focus ring */

/* glow — the prototype's entire shadow vocabulary is coloured glow, never drop shadow */
--sunil-glow-xs:  0 0 8px;   /* EXTRACTED: .panel::before, .lamp.on, .lamp.warn */
--sunil-glow-sm:  0 0 12px;  /* EXTRACTED: .stat .val text-shadow */
--sunil-glow-md:  0 0 14px;  /* EXTRACTED: .clock text-shadow (and canvas marker shadowBlur:14) */
--sunil-glow-lg:  0 0 18px;  /* EXTRACTED: h1 text-shadow */
--sunil-glow-xl:  0 0 22px;  /* EXTRACTED: #briefBtn:hover box-shadow */
--sunil-glow-2xl: 0 0 30px;  /* EXTRACTED: #briefBtn.speaking box-shadow */
--sunil-glow-3xl: 0 0 44px;  /* EXTRACTED: @keyframes btnpulse 50% */

/* elevation — INTRODUCED. The prototype is a single flat plane; a shell with */
/* drawers, menus and modals needs real occlusion or the HUD reads as broken.  */
--sunil-shadow-raised:  0 8px 24px -8px rgba(0, 0, 0, 0.72);
--sunil-shadow-overlay: 0 24px 64px -12px rgba(0, 0, 0, 0.86);

/* z-index — INTRODUCED in full; the prototype has only implicit paint order  */
--sunil-z-canvas:    0;    /* <SunilPresence /> */
--sunil-z-ambience:  1;    /* vignette + scanline overlays (pointer-events:none) */
--sunil-z-content:   10;
--sunil-z-sticky:    100;  /* sticky table headers, section headers */
--sunil-z-header:    200;  /* app header */
--sunil-z-sidebar:   300;  /* desktop sidebar; mobile drawer panel */
--sunil-z-scrim:     400;  /* drawer/modal backdrop */
--sunil-z-modal:     500;
--sunil-z-popover:   600;  /* menus, tooltips, comboboxes */
--sunil-z-toast:     700;
--sunil-z-skiplink:  800;  /* must outrank everything it skips past */

/* motion */
--sunil-duration-instant: 75ms;   /* introduced: state echo on press */
--sunil-duration-fast:    120ms;  /* introduced: hover/focus tint */
--sunil-duration-base:    180ms;  /* introduced: nav item, chip */
--sunil-duration-slow:    250ms;  /* EXTRACTED: #briefBtn{transition:all .25s} */
--sunil-duration-slower:  400ms;  /* introduced: drawer slide, modal */
--sunil-duration-pulse:   1100ms; /* EXTRACTED: btnpulse 1.1s */
--sunil-ease-standard: cubic-bezier(0.2, 0, 0, 1);
--sunil-ease-out:      cubic-bezier(0, 0, 0.2, 1);
--sunil-ease-in:       cubic-bezier(0.4, 0, 1, 1);
--sunil-ease-inout:    cubic-bezier(0.4, 0, 0.2, 1); /* EXTRACTED: btnpulse ease-in-out */

/* breakpoints — token-documented only; CSS media queries cannot read var() */
--sunil-bp-sm:  480px;
--sunil-bp-md:  768px;
--sunil-bp-lg:  1024px;
--sunil-bp-xl:  1280px;
--sunil-bp-2xl: 1536px;
```

---

## 3. Layer 2 — Semantic tokens

This is the layer a theme rebinds (§8). **Nothing here contains a literal value.**

### 3.1 Colour semantics

```css
:root, [data-theme="dark"] {
  /* ---- surfaces ---- */
  --sunil-bg:              var(--sunil-void-900);
  --sunil-surface:         var(--sunil-void-800);        /* translucent panel (prototype-faithful) */
  --sunil-surface-solid:   var(--sunil-void-800-solid);  /* opaque panel — mandatory over the canvas */
  --sunil-surface-raised:  var(--sunil-void-700);
  --sunil-surface-input:   var(--sunil-void-600);
  --sunil-surface-scrim:   var(--sunil-scrim);

  /* ---- text ---- */
  --sunil-text-primary:     var(--sunil-ice-100);   /* 17.25 on panel — dense body copy, table cells, values */
  --sunil-text-secondary:   var(--sunil-ice-500);   /* 10.43 — supporting sentences, descriptions */
  --sunil-text-muted:       #1BA3BC;                /* 6.47 — the prototype's "dim cyan" role, corrected (§6.1) */
  --sunil-text-accent:      var(--sunil-cyan-400);  /* 10.72 — brand accents, metric values, links */
  --sunil-text-heading:     var(--sunil-sky-300);   /* 11.61 — panel titles (prototype .panel h2) */
  --sunil-text-emphasis:    var(--sunil-cyan-200);  /* 15.51 — greeting / hero line (prototype .greeting) */
  --sunil-text-disabled:    var(--sunil-ice-800);   /* 6.19 — unavailable destinations, disabled controls */
  --sunil-text-placeholder: var(--sunil-ice-800);   /* 6.19 */
  --sunil-text-on-accent:   var(--sunil-void-900);  /* 11.14 on cyan-400 — text on a filled cyan surface */

  /* ---- borders ---- */
  --sunil-border-subtle:      var(--sunil-cyan-a18); /* 1.41 — DECORATIVE ONLY (panel edges, dividers) */
  --sunil-border-rule:        var(--sunil-cyan-a12); /* 1.23 — DECORATIVE ONLY (dashed row rules) */
  --sunil-border-interactive: #2E8296;               /* 4.38 — every control boundary that must be seen */
  --sunil-border-focus:       var(--sunil-cyan-300); /* 13.36 — focus ring */
  --sunil-border-danger:      var(--sunil-rose-400); /* 7.00 — invalid field boundary */

  /* ---- status ---- */
  --sunil-status-ok:       var(--sunil-emerald-400); /* 10.07 */
  --sunil-status-warn:     var(--sunil-amber-400);   /* 11.60 */
  --sunil-status-danger:   var(--sunil-rose-400);    /* 7.00 */
  --sunil-status-danger-text: var(--sunil-rose-300); /* 10.20 — error copy */
  --sunil-status-offline:  var(--sunil-slate-500);   /* 4.07 — corrected from #475569 (§6.2) */
  --sunil-status-unknown:  var(--sunil-ice-800);     /* 6.19 — "not configured / unverified" (FR-065) */

  /* ---- accent fills ---- */
  --sunil-accent-fill:        var(--sunil-cyan-400);
  --sunil-accent-tint-weak:   var(--sunil-cyan-a08); /* resting ghost button */
  --sunil-accent-tint:        var(--sunil-cyan-a12); /* active nav item */
  --sunil-accent-tint-strong: var(--sunil-cyan-a20); /* hover */
  --sunil-accent-tint-max:    var(--sunil-cyan-a28); /* pressed / speaking */
  --sunil-accent-glow:        var(--sunil-cyan-a55); /* glow colour ONLY — never a text colour */
}
```

### 3.2 Typography semantics

Every role is `font-family / size / line-height / weight / letter-spacing / transform`.
`ls` is expressed in `em` so it survives a size change; the prototype's px tracking is converted
and the source value is quoted.

| Role token | Family | Size | Line height | Weight | Tracking | Case | Origin |
|---|---|---|---|---|---|---|---|
| `--sunil-type-display-lg` | display | 34px | 40px | 800 | `0.235em` | upper | **Extracted** — `h1{font-size:34px;letter-spacing:8px;font-weight:800}` (8/34 = 0.235em) |
| `--sunil-type-display` | display | 30px | 36px | 600 | `0.06em` | none | **Extracted** — `.clock{font-size:30px;font-weight:600}` |
| `--sunil-type-display-sm` | display | 22px | 28px | 600 | `0.04em` | none | **Extracted** — `.stat .val{font-size:22px;font-weight:600}` |
| `--sunil-type-title` | display | 18px | 24px | 600 | `0.08em` | none | **Introduced** — page titles; the prototype has no page-title role |
| `--sunil-type-eyebrow` | display | 11px | 16px | 600 | `0.273em` | upper | **Extracted** — `.panel h2{font-size:11px;letter-spacing:3px;font-weight:600;text-transform:uppercase}` (3/11) |
| `--sunil-type-action` | display | 13px | 20px | 600 | `0.308em` | upper | **Extracted** — `#briefBtn{font-size:13px;letter-spacing:4px;font-weight:600}` (4/13) |
| `--sunil-type-body` | mono | 14px | 22px | 400 | `0` | none | **Introduced** — the prototype's largest body size is 13px; 14px is the shell's reading size |
| `--sunil-type-body-sm` | mono | 13px | 20px | 400 | `0.02em` | none | **Extracted** — `.greeting{font-size:13px;letter-spacing:2px}` (tracking reduced, see §6.4) |
| `--sunil-type-caption` | mono | 12px | 18px | 400 | `0.08em` | none | **Extracted** — `.datestamp`, `.sysrow`, `.queue-item`, `.clock small{font-size:12px}` |
| `--sunil-type-micro` | mono | 11px | 16px | 400 | `0.18em` | upper | **Corrected** — replaces the prototype's 10px micro labels (`.state`, `.stat .lbl`, `.queue-item .when`). See §6.4 |

Global: `body { font-family: var(--sunil-font-mono); font-size: 14px; line-height: 22px; color: var(--sunil-text-primary); }`
— the prototype sets `body{font-family:'Share Tech Mono';color:var(--cyan)}`; the family is
faithful, the default colour changes from cyan to ice-100 (§6.3).

### 3.3 Motion semantics

```css
--sunil-motion-hover:   var(--sunil-duration-fast)  var(--sunil-ease-out);
--sunil-motion-control: var(--sunil-duration-base)  var(--sunil-ease-standard);
--sunil-motion-surface: var(--sunil-duration-slower) var(--sunil-ease-standard); /* drawer, modal */
--sunil-motion-emphasis: var(--sunil-duration-slow) var(--sunil-ease-inout);     /* prototype .25s */
```

**Reduced motion is a token-level contract, not a per-component afterthought:**

```css
@media (prefers-reduced-motion: reduce) {
  :root {
    --sunil-duration-instant: 0.01ms; --sunil-duration-fast:   0.01ms;
    --sunil-duration-base:    0.01ms; --sunil-duration-slow:   0.01ms;
    --sunil-duration-slower:  0.01ms; --sunil-duration-pulse:  0.01ms;
  }
  *, *::before, *::after {
    animation-duration: 0.01ms !important; animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important; scroll-behavior: auto !important;
  }
}
```

`0.01ms` rather than `0` so that `transitionend`/`animationend` handlers still fire and no state
machine stalls. `<SunilPresence />` is **not** covered by this rule — a canvas ignores CSS — and
has its own mandatory behaviour in `SUNIL_PRESENCE_SPEC.md` §8.

---

## 4. Layer 3 — Component tokens

Component tokens exist so a component's appearance can be retuned without touching its code and
without disturbing any sibling. Only the Phase 1 surface is tokenised here; Phase 2+ components
add their own block.

```css
/* ---- App shell ---- */
--sunil-shell-sidebar-w:          264px;
--sunil-shell-sidebar-w-rail:     72px;
--sunil-shell-drawer-w:           288px;
--sunil-shell-header-h:           64px;
--sunil-shell-header-h-compact:   56px;
--sunil-shell-content-max:        1440px;
--sunil-shell-pad-x:              var(--sunil-space-24);
--sunil-shell-pad-x-compact:      var(--sunil-space-16);
--sunil-shell-bg:                 var(--sunil-bg);
--sunil-shell-header-bg:          var(--sunil-surface-solid);
--sunil-shell-header-border:      var(--sunil-border-subtle);

/* ---- Nav item ---- */
--sunil-nav-item-h:            40px;
--sunil-nav-item-pad-x:        var(--sunil-space-12);
--sunil-nav-item-gap:          var(--sunil-space-10);
--sunil-nav-item-radius:       var(--sunil-radius-4);
--sunil-nav-item-fg:           var(--sunil-text-secondary);
--sunil-nav-item-fg-hover:     var(--sunil-text-primary);
--sunil-nav-item-fg-active:    var(--sunil-text-accent);
--sunil-nav-item-fg-disabled:  var(--sunil-text-disabled);
--sunil-nav-item-bg-hover:     var(--sunil-accent-tint-weak);
--sunil-nav-item-bg-active:    var(--sunil-accent-tint);
--sunil-nav-item-marker-w:     var(--sunil-border-2);
--sunil-nav-item-marker:       var(--sunil-accent-fill);
--sunil-nav-group-fg:          var(--sunil-text-muted);

/* ---- Panel (prototype .panel) ---- */
--sunil-panel-bg:            var(--sunil-surface);
--sunil-panel-bg-opaque:     var(--sunil-surface-solid);
--sunil-panel-border:        var(--sunil-border-subtle);
--sunil-panel-radius:        var(--sunil-radius-6);
--sunil-panel-pad:           var(--sunil-space-16);
--sunil-panel-pad-y:         var(--sunil-space-14);
--sunil-panel-blur:          3px;                  /* EXTRACTED: backdrop-filter:blur(3px) */
--sunil-panel-accent-w:      46px;                 /* EXTRACTED: .panel::before{width:46px} */
--sunil-panel-accent-inset:  var(--sunil-space-12);/* EXTRACTED: .panel::before{left:12px} */
--sunil-panel-accent-glow:   var(--sunil-glow-xs) var(--sunil-accent-fill);
--sunil-panel-title-fg:      var(--sunil-text-heading);
--sunil-panel-title-mb:      var(--sunil-space-12);/* EXTRACTED: .panel h2{margin-bottom:12px} */

/* ---- Button ---- */
--sunil-btn-h:               40px;
--sunil-btn-h-sm:            32px;
--sunil-btn-pad-x:           var(--sunil-space-20);
--sunil-btn-radius:          var(--sunil-radius-6);
--sunil-btn-primary-bg:      var(--sunil-accent-fill);
--sunil-btn-primary-fg:      var(--sunil-text-on-accent);
--sunil-btn-ghost-bg:        var(--sunil-accent-tint-weak);
--sunil-btn-ghost-bg-hover:  var(--sunil-accent-tint-strong);
--sunil-btn-ghost-fg:        var(--sunil-text-accent);
--sunil-btn-ghost-border:    var(--sunil-border-interactive);
--sunil-btn-glow-hover:      var(--sunil-glow-xl) var(--sunil-cyan-a18);

/* ---- Field ---- */
--sunil-field-h:             44px;
--sunil-field-pad-x:         var(--sunil-space-12);
--sunil-field-radius:        var(--sunil-radius-4);
--sunil-field-bg:            var(--sunil-surface-input);
--sunil-field-border:        var(--sunil-border-interactive);
--sunil-field-border-focus:  var(--sunil-border-focus);
--sunil-field-border-error:  var(--sunil-border-danger);
--sunil-field-fg:            var(--sunil-text-primary);
--sunil-field-placeholder:   var(--sunil-text-placeholder);
--sunil-field-label-fg:      var(--sunil-text-muted);
--sunil-field-hint-fg:       var(--sunil-text-secondary);
--sunil-field-error-fg:      var(--sunil-status-danger-text);

/* ---- Lamp (prototype .lamp) ---- */
--sunil-lamp-size:           8px;                  /* EXTRACTED */
--sunil-lamp-glow:           var(--sunil-glow-xs); /* EXTRACTED */
--sunil-lamp-on:             var(--sunil-status-ok);
--sunil-lamp-warn:           var(--sunil-status-warn);
--sunil-lamp-error:          var(--sunil-status-danger);
--sunil-lamp-off:            var(--sunil-status-offline);
--sunil-lamp-unknown:        var(--sunil-status-unknown);

/* ---- Badge / chip (e.g. "PHASE 2") ---- */
--sunil-badge-h:             18px;
--sunil-badge-pad-x:         var(--sunil-space-6);
--sunil-badge-radius:        var(--sunil-radius-2);
--sunil-badge-bg:            var(--sunil-accent-tint-weak);
--sunil-badge-fg:            var(--sunil-ice-500);
--sunil-badge-border:        var(--sunil-border-subtle);

/* ---- Focus ring (global) ---- */
--sunil-focus-w:             var(--sunil-border-2);
--sunil-focus-offset:        2px;
--sunil-focus-color:         var(--sunil-border-focus);

/* ---- Presence canvas ---- */
--sunil-presence-size-sm:    200px;
--sunil-presence-size-md:    320px;
--sunil-presence-size-lg:    440px;
--sunil-presence-point:      var(--sunil-cyan-300);
--sunil-presence-arc:        var(--sunil-cyan-400);
--sunil-presence-marker:     var(--sunil-cyan-200);
--sunil-presence-glow:       var(--sunil-cyan-400);

/* ---- Skeleton / loading ---- */
--sunil-skeleton-bg:         #0E1E2C;   /* 1.14 on panel — a shape, never text */
--sunil-skeleton-sheen:      #16303C;   /* 1.40 on panel */
--sunil-skeleton-radius:     var(--sunil-radius-4);
```

---

## 5. Contrast audit (WCAG 2.1)

### 5.1 Method — stated so it can be reproduced and challenged

- Relative luminance per WCAG 2.1: channel `c/255`, linearised as `c ≤ 0.03928 ? c/12.92 :
  ((c+0.055)/1.055)^2.4`, then `L = 0.2126R + 0.7152G + 0.0722B`.
- Contrast `= (L_lighter + 0.05) / (L_darker + 0.05)`.
- **Alpha is composited before measurement**, `result = α·fg + (1−α)·bg`. A ratio quoted for an
  `rgba()` value without stating its backdrop is meaningless, which is precisely how R-10 went
  unnoticed until now.
- Thresholds: **4.5:1** normal text; **3:1** large text (≥24px regular or ≥18.66px bold — the
  prototype's `h1` 34px/800, `.clock` 30px/600 and `.stat .val` 22px/600 all qualify as large;
  everything at 13px and below does not); **3:1** non-text UI components and graphical objects
  required for understanding (SC 1.4.11).
- Ratios computed with `node`, full precision, rounded to 2dp for display.

**Four backdrops are tested**, because the shell is not painted on one colour:

| Backdrop | Derivation | Composited value | Relative luminance |
|---|---|---|---|
| `bg` | `--bg:#030712` | `#030712` | 0.00325 |
| `panel(eff)` | `rgba(7,16,32,.72)` over `#030712` | `#060D1C` | 0.00422 |
| `glow-idle` | canvas core glow `rgba(34,211,238,.12)` over bg | `#071F2C` | 0.01233 |
| `glow-speak` | canvas core glow `rgba(34,211,238,.20)` over bg | `#09303E` | 0.02505 |

`glow-speak` is the **worst-case bound** for anything drawn over the presence canvas: it is the
brightest backdrop the shell can produce, and a translucent panel over it composites *darker*
than the raw glow, so any pair that passes on `glow-speak` passes everywhere. The `.vignette`
(`rgba(0,0,5,.75)` at the edges) and `.scanlines` (5% `#67e8f9`) both sit **below** the HUD layer
in paint order, so they never overlay text; the vignette only darkens, which helps.

### 5.2 Full pair audit — prototype values exactly as written

60 pairs (15 foreground values × 4 backdrops). **PASS/FAIL is stated per threshold; a "—" means
the threshold does not apply to that value's actual role in the product.**

| # | Foreground (prototype source) | Backdrop | Composited fg | Ratio | AA normal 4.5 | AA large 3.0 | UI 3.0 |
|---|---|---|---|---|---|---|---|
| 1 | `--cyan #22d3ee` | bg | `#22D3EE` | **11.14** | PASS | PASS | PASS |
| 2 | `--cyan #22d3ee` | panel(eff) | `#22D3EE` | **10.72** | PASS | PASS | PASS |
| 3 | `--cyan #22d3ee` | glow-idle | `#22D3EE` | **9.32** | PASS | PASS | PASS |
| 4 | `--cyan #22d3ee` | glow-speak | `#22D3EE` | **7.74** | PASS | PASS | PASS |
| 5 | `--cyan-dim rgba(34,211,238,.55)` | bg | `#14778B` | **3.88** | **FAIL** | PASS | PASS |
| 6 | `--cyan-dim` | panel(eff) | `#157A90` | **3.89** | **FAIL** | PASS | PASS |
| 7 | `--cyan-dim` | glow-idle | `#168297` | **3.76** | **FAIL** | PASS | PASS |
| 8 | `--cyan-dim` | glow-speak | `#178A9F` | **3.43** | **FAIL** | PASS | PASS |
| 9 | `--cyan-faint rgba(34,211,238,.18)` | bg | `#092C3A` | **1.37** | **FAIL** | **FAIL** | **FAIL** |
| 10 | `--cyan-faint` | panel(eff) | `#0B3142` | **1.41** | **FAIL** | **FAIL** | **FAIL** |
| 11 | `--cyan-faint` | glow-idle | `#0C404F` | **1.49** | **FAIL** | **FAIL** | **FAIL** |
| 12 | `--cyan-faint` | glow-speak | `#0E4D5E` | **1.50** | **FAIL** | **FAIL** | **FAIL** |
| 13 | `.panel h2 #7dd3fc` | bg | `#7DD3FC` | **12.08** | PASS | PASS | PASS |
| 14 | `.panel h2 #7dd3fc` | panel(eff) | `#7DD3FC` | **11.61** | PASS | PASS | PASS |
| 15 | `.panel h2 #7dd3fc` | glow-idle | `#7DD3FC` | **10.10** | PASS | PASS | PASS |
| 16 | `.panel h2 #7dd3fc` | glow-speak | `#7DD3FC` | **8.39** | PASS | PASS | PASS |
| 17 | `.greeting #a5f3fc` | bg | `#A5F3FC` | **16.13** | PASS | PASS | PASS |
| 18 | `.greeting #a5f3fc` | panel(eff) | `#A5F3FC` | **15.51** | PASS | PASS | PASS |
| 19 | `.greeting #a5f3fc` | glow-idle | `#A5F3FC` | **13.50** | PASS | PASS | PASS |
| 20 | `.greeting #a5f3fc` | glow-speak | `#A5F3FC` | **11.21** | PASS | PASS | PASS |
| 21 | sphere point `#67e8f9` | bg | `#67E8F9` | **13.89** | PASS | PASS | PASS |
| 22 | sphere point `#67e8f9` | panel(eff) | `#67E8F9` | **13.36** | PASS | PASS | PASS |
| 23 | sphere point `#67e8f9` | glow-idle | `#67E8F9` | **11.62** | PASS | PASS | PASS |
| 24 | sphere point `#67e8f9` | glow-speak | `#67E8F9` | **9.65** | PASS | PASS | PASS |
| 25 | `--amber #fbbf24` | bg | `#FBBF24` | **12.06** | PASS | PASS | PASS |
| 26 | `--amber #fbbf24` | panel(eff) | `#FBBF24` | **11.60** | PASS | PASS | PASS |
| 27 | `--amber #fbbf24` | glow-idle | `#FBBF24` | **10.09** | PASS | PASS | PASS |
| 28 | `--amber #fbbf24` | glow-speak | `#FBBF24` | **8.38** | PASS | PASS | PASS |
| 29 | `--ok #34d399` | bg | `#34D399` | **10.47** | PASS | PASS | PASS |
| 30 | `--ok #34d399` | panel(eff) | `#34D399` | **10.07** | PASS | PASS | PASS |
| 31 | `--ok #34d399` | glow-idle | `#34D399` | **8.76** | PASS | PASS | PASS |
| 32 | `--ok #34d399` | glow-speak | `#34D399` | **7.28** | PASS | PASS | PASS |
| 33 | `.delta.down #f87171` | bg | `#F87171` | **7.28** | PASS | PASS | PASS |
| 34 | `.delta.down #f87171` | panel(eff) | `#F87171` | **7.00** | PASS | PASS | PASS |
| 35 | `.delta.down #f87171` | glow-idle | `#F87171` | **6.09** | PASS | PASS | PASS |
| 36 | `.delta.down #f87171` | glow-speak | `#F87171` | **5.06** | PASS | PASS | PASS |
| 37 | `.lamp.off #475569` | bg | `#475569` | **2.66** | — | — | **FAIL** |
| 38 | `.lamp.off #475569` | panel(eff) | `#475569` | **2.56** | — | — | **FAIL** |
| 39 | `.lamp.off #475569` | glow-idle | `#475569` | **2.22** | — | — | **FAIL** |
| 40 | `.lamp.off #475569` | glow-speak | `#475569` | **1.85** | — | — | **FAIL** |
| 41 | row rule `rgba(34,211,238,.12)` | bg | `#071F2C` | **1.20** | — | — | exempt¹ |
| 42 | row rule | panel(eff) | `#092535` | **1.23** | — | — | exempt¹ |
| 43 | row rule | glow-idle | `#0A3544` | **1.29** | — | — | exempt¹ |
| 44 | row rule | glow-speak | `#0C4353` | **1.30** | — | — | exempt¹ |
| 45 | orbit ring `rgba(34,211,238,.4)` | bg | `#0F596A` | **2.54** | — | — | exempt² |
| 46 | orbit ring | panel(eff) | `#115C70` | **2.59** | — | — | exempt² |
| 47 | orbit ring | glow-idle | `#12677A` | **2.61** | — | — | exempt² |
| 48 | orbit ring | glow-speak | `#137184` | **2.48** | — | — | exempt² |
| 49 | HUD arc 1 `rgba(34,211,238,.5)` | bg | `#136D80` | **3.38** | — | — | exempt² |
| 50 | HUD arc 1 | panel(eff) | `#147085` | **3.41** | — | — | exempt² |
| 51 | HUD arc 1 | glow-idle | `#14798D` | **3.34** | — | — | exempt² |
| 52 | HUD arc 1 | glow-speak | `#168196` | **3.09** | — | — | exempt² |
| 53 | HUD arc 3 `rgba(34,211,238,.25)` | bg | `#0B3A49` | **1.64** | — | — | exempt² |
| 54 | HUD arc 3 | panel(eff) | `#0D3F51` | **1.70** | — | — | exempt² |
| 55 | HUD arc 3 | glow-idle | `#0E4C5D` | **1.78** | — | — | exempt² |
| 56 | HUD arc 3 | glow-speak | `#0F596A` | **1.76** | — | — | exempt² |
| 57 | scanline `#67e8f9 @ .05` | bg | `#08121E` | **1.07** | — | — | exempt² |
| 58 | scanline | panel(eff) | `#0B1827` | **1.09** | — | — | exempt² |
| 59 | scanline | glow-idle | `#0C2A37` | **1.12** | — | — | exempt² |
| 60 | scanline | glow-speak | `#0E3947` | **1.13** | — | — | exempt² |

¹ SC 1.4.11 applies to boundaries **required to identify a control**. A dashed rule separating two
list rows is a decorative divider; the rows are identifiable from their content and spacing. Kept
as-is, but it may **never** be the border of an input, button or focusable row.
² Purely decorative canvas ornament conveying no information (SC 1.4.11 exception). Its
information role is carried by the accessible status text specified in `SUNIL_PRESENCE_SPEC.md` §8.3.

**Headline result: 60 pairs tested; 32 fall below 4.5:1; 24 fall below 3:1. The single worst
ratio is 1.07:1 (the scanline overlay on `--bg`), which is decorative and exempt. The worst
in-scope failure is `--cyan-dim` at 3.43:1 over the speaking glow, against a 4.5:1 requirement —
and because `--cyan-dim` is the colour of almost every label, unit, timestamp and state string in
the prototype, this single token is the whole of R-10.**

Reducing to values whose *role* imposes a threshold, there are exactly **three token-level
defects** (12 of the 60 pairs):

| Defect | Token | Role in the prototype | Requirement | Worst measured | Verdict |
|---|---|---|---|---|---|
| **D-1** | `--cyan-dim rgba(34,211,238,.55)` | `.subtitle`, `.datestamp`, `.clock small`, `.sysrow .state`, `.stat .lbl` — all 10–12px | 4.5:1 | **3.43** | **FAIL** — must change |
| **D-2** | `.lamp.off #475569` | connector status indicator, 8px dot | 3:1 (SC 1.4.11) | **1.85** | **FAIL** — must change |
| **D-3** | `--cyan-faint rgba(34,211,238,.18)` | `.panel` border — *decorative, passes by exemption*. But it is the **only** border value the prototype owns, so any input or button that reuses it inherits a 1.41:1 control boundary | 3:1 when used on a control | **1.37** | **CONDITIONAL FAIL** — safe on panels, unusable on controls; a distinct token is required |

### 5.3 Corrected token set — computed ratios

Every text and UI token in §3.1, measured on all four backdrops.

| Semantic token | Value | bg | panel(eff) | glow-idle | glow-speak | Required | Verdict |
|---|---|---|---|---|---|---|---|
| `--sunil-text-primary` | `#E3F5FA` | 17.94 | 17.25 | 15.01 | 12.46 | 4.5 | PASS (worst 12.46) |
| `--sunil-text-secondary` | `#9AC5D4` | 10.84 | 10.43 | 9.06 | 7.54 | 4.5 | PASS (worst 7.54) |
| `--sunil-text-muted` | `#1BA3BC` | 6.72 | 6.47 | 5.62 | 4.67 | 4.5 | PASS (worst 4.67) |
| `--sunil-text-accent` | `#22D3EE` | 11.14 | 10.72 | 9.32 | 7.74 | 4.5 | PASS (worst 7.74) |
| `--sunil-text-heading` | `#7DD3FC` | 12.08 | 11.61 | 10.10 | 8.39 | 4.5 | PASS (worst 8.39) |
| `--sunil-text-emphasis` | `#A5F3FC` | 16.13 | 15.51 | 13.50 | 11.21 | 4.5 | PASS (worst 11.21) |
| `--sunil-text-disabled` | `#6499AE` | 6.43 | 6.19 | 5.38 | 4.47 | 4.5* | PASS on all shell surfaces; see note |
| `--sunil-text-placeholder` | `#6499AE` | 6.43 | 6.19 | — | — | 4.5 | PASS |
| `--sunil-text-on-accent` | `#030712` on `#22D3EE` | 11.14 | — | — | — | 4.5 | PASS |
| `--sunil-border-interactive` | `#2E8296` | 4.55 | 4.38 | 3.81 | 3.16 | 3.0 | PASS (worst 3.16) |
| `--sunil-border-focus` | `#67E8F9` | 13.89 | 13.36 | 11.62 | 9.65 | 3.0 | PASS (worst 9.65) |
| `--sunil-border-danger` | `#F87171` | 7.28 | 7.00 | 6.09 | 5.06 | 3.0 | PASS |
| `--sunil-status-ok` | `#34D399` | 10.47 | 10.07 | 8.76 | 7.28 | 3.0 | PASS |
| `--sunil-status-warn` | `#FBBF24` | 12.06 | 11.60 | 10.09 | 8.38 | 3.0 | PASS |
| `--sunil-status-danger` | `#F87171` | 7.28 | 7.00 | 6.09 | 5.06 | 3.0 | PASS |
| `--sunil-status-danger-text` | `#FCA5A5` | 10.61 | 10.20 | 8.88 | 7.37 | 4.5 | PASS |
| `--sunil-status-offline` | `#64748B` | 4.23 | 4.07 | 3.54 | 2.94 | 3.0 | PASS on all shell surfaces; **must not be drawn over the presence glow** |
| `--sunil-status-unknown` | `#6499AE` | 6.43 | 6.19 | 5.38 | 4.47 | 3.0 | PASS |
| `--sunil-badge-fg` on `--sunil-badge-bg` | `#9AC5D4` on `#092131` | — | 8.87 | — | — | 4.5 | PASS |
| `--sunil-nav-item-fg-active` on `--sunil-nav-item-bg-active` | `#22D3EE` on `#092535` | — | 8.73 | — | — | 4.5 | PASS |
| `--sunil-btn-primary-fg` on `--sunil-btn-primary-bg` | `#030712` on `#22D3EE` | — | 11.14 | — | — | 4.5 | PASS |

\* `--sunil-text-disabled` and `--sunil-status-offline` measure 4.47 and 2.94 respectively **on the
speaking glow only**. Neither is ever painted there: disabled nav items live in the sidebar and
offline lamps live inside panels, both of which are shell surfaces. **This is a hard placement
constraint, not a caveat to be forgotten** — see §5.4.

### 5.4 Rules that make the numbers hold at build time

These are the difference between "the palette passes" and "the product passes". They belong in
code review and in the automated a11y scan (BL-806).

1. **No `rgba()` value may ever be a text colour.** Text over the presence canvas has an
   indeterminate backdrop; alpha text has an indeterminate ratio. Every `--sunil-text-*` token is
   opaque, and that is the reason.
2. **Nothing dimmer than `--sunil-text-muted` (`#1BA3BC`, worst case 4.67) may sit over the
   canvas.** `--sunil-text-disabled` and `--sunil-status-offline` are shell-surface-only.
3. **Any text region overlapping the presence canvas must sit on `--sunil-surface-scrim` or on an
   opaque panel** (`--sunil-surface-solid`). Measured: `--sunil-text-accent` on
   `rgba(3,7,18,.82)` over the worst-case glow = **10.71**; `--sunil-text-secondary` = **10.43**.
   The scrim removes the problem entirely rather than managing it.
4. **`--sunil-border-subtle` and `--sunil-border-rule` are decorative-only tokens.** A lint rule
   should reject them on `input`, `select`, `textarea`, `button` or any element with `tabindex`.
   Controls use `--sunil-border-interactive`.
5. **Never use `text-shadow` glow on text below 18.66px.** Glow spreads the glyph edge and eats
   the measured contrast at small sizes. The prototype only glows 22px+ text; keep that discipline
   — it was correct by accident and must become correct by rule.
6. **Colour is never the only channel.** Every lamp carries a text state (the prototype already
   does this with `.sysrow .state`), every metric delta carries the ▲/▼ glyph it already has, and
   every field error carries text, not just a red border (SC 1.4.1).
7. **The `.scanlines` overlay must stay below the content layer** (`--sunil-z-ambience: 1`). If it
   is ever painted above text it re-introduces a 5% luminance veil over every glyph in the
   product.

---

## 6. Deviation register — original → corrected

Recorded per FR-100 ("any deliberate deviation is recorded by the UI/UX designer"). **Nothing here
is a silent restyle. Each row is a conflict between the locked aesthetic and NFR-016, decided in
favour of NFR-016, with the visual cost stated.**

### 6.1 D-1 — the dim-cyan text token (the material change)

| | Value | Worst ratio | Note |
|---|---|---|---|
| **Original** | `--cyan-dim: rgba(34,211,238,.55)` | **3.43** | Fails 4.5:1 on every backdrop |
| **Corrected (recommended)** | `--sunil-text-muted: #1BA3BC` | **4.67** | Opaque; same hue family; minimum viable change |
| Alternative A (most faithful, zero margin) | `#17859C` | 3.25 on glow-speak, 4.49 on panel | **Rejected** — fails on the canvas and misses 4.5 on the panel by 0.01 |
| Alternative B (safer margin) | `#1BA3BC` at 12px+ only, `#9AC5D4` at 11px | 4.67 / 7.54 | Available if the a11y scan flags real-world rendering |

**The design trade-off, stated plainly for the human:** on a `#030712` background you cannot make
text *dimmer* and keep it legible — dimness and contrast failure are the same physical quantity.
The prototype's hierarchy ("bright cyan for values, dim cyan for labels") therefore cannot survive
as-is. The corrected system keeps the *hue* and rebuilds the hierarchy from **saturation, size and
tracking** instead of luminance: labels stay 11px uppercase with 0.18em tracking in a saturated
mid-cyan; values stay large and bright. Side by side, corrected labels read as slightly more
present than the prototype's. That is the visible cost, and it is the smallest one available.

**If the owner wants to keep the alpha formulation**, there is a valid minimum change. The alpha
needed to reach 4.5:1 was solved numerically per backdrop:

| Backdrop | Minimum α of `#22d3ee` for 4.5:1 | Composited result |
|---|---|---|
| bg `#030712` | 0.605 | `#168297` |
| panel(eff) `#060D1C` | 0.607 | `#17859C` |
| glow-idle | 0.630 | `#1891A6` |
| glow-speak (worst) | **0.688** | `#1AA0B7` |

So `rgba(34,211,238,.72)` clears every backdrop, worst case **4.79:1** (measured over the speaking
glow; 5.93:1 over the panel). It is the single most faithful correction available — one number
changed, `.55` → `.72`.

**Why the opaque token is still recommended over it.** Alpha text is self-referential: its ratio
is a function of whatever happens to be painted behind it. Those four backdrops are the ones that
exist *today*. The moment a raised menu, a modal surface, a hover tint or a selected-row highlight
is introduced — all of which this phase introduces — the ratio changes silently and nothing in the
build catches it. `#1BA3BC` is invariant: measure it once, and it stays measured. The alpha option
is nonetheless a legitimate choice and is recorded here with its numbers so the human can take it
knowingly.

### 6.2 D-2 — the offline lamp

| | Value | Ratio (panel) | Ratio (worst) |
|---|---|---|---|
| **Original** | `.lamp.off { background:#475569 }` | 2.56 | 1.85 |
| **Corrected** | `--sunil-status-offline: #64748B` | **4.07** | 2.94 (glow only — never painted there) |

An 8px dot is the sole graphical carrier of "this connector is offline" and therefore falls under
SC 1.4.11 at 3:1. The correction is one Tailwind step lighter and is essentially invisible as a
design change. The accompanying text state (`OFFLINE`) remains mandatory regardless.

### 6.3 D-3 — default body colour

| | Value | Note |
|---|---|---|
| **Original** | `body { color: var(--cyan) }` → `#22D3EE` | Passes contrast (10.72) but is fully saturated cyan for **all** text |
| **Corrected** | `body { color: var(--sunil-text-primary) }` → `#E3F5FA` | 17.25 |

Not a contrast fix — a legibility and scale fix. The prototype displays about 30 words of text.
The shell displays audit tables, log lines, settings forms and error messages. Saturated cyan at
paragraph length on near-black produces chromatic aberration and after-images for most readers,
and it removes the ability to use cyan as an *accent* because everything is already cyan. Cyan is
retained for values, links, active nav and headings, where it still reads as the SUNIL voice.

### 6.4 Type-size corrections

| Prototype | Corrected | Reason |
|---|---|---|
| `.sysrow .state`, `.stat .lbl` at **10px** with 2px tracking | **11px** with 0.18em tracking (`--sunil-type-micro`) | 10px uppercase mono with heavy tracking is at the edge of legibility for the smallest text in the product, and these strings (`ONLINE`, `STANDBY`, `OFFLINE`) carry status meaning. 11px is the floor for the whole design system |
| `.greeting` 13px with **2px** (0.154em) tracking | 13px with **0.02em** | 0.154em tracking on a full sentence harms reading speed. Heavy tracking is retained where it belongs — uppercase eyebrows, buttons, the wordmark |
| `#briefBtn` 4px (0.308em) tracking | Retained at 0.308em | Single short uppercase label; the tracking is the aesthetic and costs nothing |

### 6.5 Spacing normalisation

| Prototype | Corrected | Reason |
|---|---|---|
| `.hud { padding: 26px }` | `--sunil-shell-pad-x: 24px` | 26px is off the 4px grid; 2px is imperceptible |
| `.hud { gap: 18px }` | `16px` | Same |
| `.stat { padding: 12px 22px }` | `12px 20px` | Same |

### 6.6 Things deliberately **not** changed

- `--sunil-cyan-400 #22D3EE`, `--sunil-bg #030712`, `--sunil-void-800 rgba(7,16,32,.72)`,
  `--sunil-amber-400 #FBBF24`, `--sunil-emerald-400 #34D399` — locked by `SUNIL_ARCHITECTURE.md` §3
  and all pass their thresholds. No change proposed and none needed.
- `--sunil-radius-6`, `--sunil-panel-accent-w: 46px`, `--sunil-panel-accent-inset: 12px`,
  `--sunil-lamp-size: 8px`, `--sunil-panel-blur: 3px` — carried verbatim. These small oddities
  *are* the HUD's fingerprint.
- The scanline and vignette overlays — carried verbatim, with the paint-order rule in §5.4.7.
- `.panel h2 #7dd3fc` — a sky-tinted heading inside a cyan system looks like an accident but reads
  as deliberate at 11.61:1. Kept.

---

## 7. Font loading strategy

### 7.1 Decision: self-host. Do not use the Google Fonts CDN.

The prototype uses `<link href="https://fonts.googleapis.com/css2?family=Orbitron…">`. That
cannot ship, for three independent reasons:

1. **FR-031 / NFR-004 require a strict CSP.** The CDN link needs `style-src fonts.googleapis.com`
   and `font-src fonts.gstatic.com`, weakening the policy for a decorative asset.
2. **Two extra DNS + TLS round trips before first text paint**, against NFR-007's 3-second
   interactive budget.
3. Phase 1 is local-only (A-01) and must work on a machine with no internet route to Google.

Self-host as `woff2` under `apps/web/public/fonts/`, served `font-src 'self'`, with
`Cache-Control: public, max-age=31536000, immutable`.

### 7.2 Files and weights

| Family | File | Weights | Preload | Used for |
|---|---|---|---|---|
| Orbitron | `orbitron-variable.woff2` (variable, 400–900, latin subset) | 400 / 600 / 800 via `font-variation-settings` | **Yes** | Wordmark, clock, panel eyebrows, stat values, buttons |
| Share Tech Mono | `share-tech-mono-400.woff2` (static, latin subset) | 400 only | **Yes** | Everything else — it is the body face |

Orbitron ships as a variable font, so all three weights the prototype uses come from one file. Do
not load three static cuts. Subset to `latin` (A-13: en-AU only); do not subset further —
`latin-ext` removal is safe, glyph-level subsetting is not, because audit payloads and error
strings can contain arbitrary text.

`font-synthesis: none` globally. Neither family has an italic or a true bold beyond its axis, and
synthesised faces destroy Orbitron's geometry.

### 7.3 Avoiding layout shift — the actual mechanism

`font-display: swap` is correct (never `block`: invisible text on a security-critical sign-in page
is a usability failure), **but swap is exactly what causes CLS**. The fix is a metric-matched
fallback so the fallback occupies the same box as the real face:

```css
/* Generated, not hand-written. Values below are illustrative placeholders — */
/* the engineer MUST regenerate them from the shipped .woff2 files.          */
@font-face {
  font-family: 'Orbitron Fallback';
  src: local('Trebuchet MS'), local('Arial');
  ascent-override: 96.5%; descent-override: 24.1%; line-gap-override: 0%; size-adjust: 103.2%;
}
@font-face {
  font-family: 'Share Tech Mono Fallback';
  src: local('Consolas'), local('Cascadia Mono'), local('Courier New');
  ascent-override: 92.0%; descent-override: 22.0%; line-gap-override: 0%; size-adjust: 101.0%;
}
```

**Preferred implementation:** use `next/font/local` with `adjustFontFallback` enabled. It reads the
real font metrics at build time and emits the correct overrides automatically — the engineer never
hand-tunes the four percentages above, and they cannot drift when a font file is replaced.

```ts
// apps/web/app/fonts.ts  (illustrative — this is the shape, not the app code)
import localFont from 'next/font/local';

export const orbitron = localFont({
  src: '../public/fonts/orbitron-variable.woff2',
  variable: '--sunil-font-display-loaded',
  display: 'swap',
  preload: true,
  fallback: ['Trebuchet MS', 'ui-sans-serif', 'system-ui', 'sans-serif'],
  adjustFontFallback: 'Arial',
});

export const shareTechMono = localFont({
  src: '../public/fonts/share-tech-mono-400.woff2',
  variable: '--sunil-font-mono-loaded',
  display: 'swap',
  preload: true,
  fallback: ['ui-monospace', 'Cascadia Mono', 'Consolas', 'Courier New', 'monospace'],
  adjustFontFallback: 'Arial',
});
```

If `next/font` is not used, generate the overrides with a metrics tool
(`fontkit` / `capsize` / `fontpie`) as a build step and commit the generated `@font-face` block —
never estimate them by eye.

**Acceptance:** Cumulative Layout Shift attributable to font swap must be **0.00** on the sign-in
page and the dashboard, measured with the network throttled so the swap is observable. If it is
non-zero, the overrides are wrong, not the strategy.

### 7.4 Fallback stacks (authoritative)

```
display: 'Orbitron', 'Orbitron Fallback', 'Trebuchet MS', ui-sans-serif, system-ui, sans-serif
mono:    'Share Tech Mono', 'Share Tech Mono Fallback', ui-monospace, 'Cascadia Mono', Consolas, 'Courier New', monospace
```

Windows 11 is the reference platform (NFR-017), so `Consolas` and `Cascadia Mono` — both present
on every Windows 11 install — lead the real-world mono fallback. Verify the fallback rendering by
blocking `/fonts/*` in devtools: the layout must be identical, only the letterforms different.

### 7.5 Tabular figures

The clock, usage counters, health latencies and audit timestamps all update in place. Apply
`font-variant-numeric: tabular-nums; font-feature-settings: 'tnum' 1;` to
`--sunil-type-display`, `--sunil-type-display-sm` and any numeric cell. Share Tech Mono is already
monospaced; Orbitron is not, and an untreated clock will jitter every second.

---

## 8. How a light theme drops in later (without restructuring)

Phase 1 ships dark only (FR-103). The structure that makes a second theme cheap:

1. **Only §3 changes.** A light theme is a second `[data-theme="light"]` block that rebinds the
   ~35 semantic tokens. Primitives (§2) are theme-agnostic raw values; component tokens (§4) point
   at semantics and never at primitives, so **no component CSS is touched**.
2. **Surfaces are named by elevation, not by colour.** `--sunil-surface-raised` means "one level
   above the panel". In dark that is lighter; in light it will be darker or shadowed. Had the
   tokens been named `--sunil-navy-panel`, every name would lie in light mode.
3. **Text tokens are named by role, not by lightness.** `--sunil-text-muted` inverts cleanly;
   `--sunil-text-light-blue` would not.
4. **`color-scheme`.** Set `color-scheme: dark` on `:root` now (and `light` in the future block) so
   native scrollbars, form controls and the browser's own focus fall in line automatically.
5. **The ice ramp already runs both directions.** Light mode reads it from the dark end:
   `--sunil-text-primary: var(--sunil-ice-900)` etc. The cyan ramp likewise — `#0E7490` gives
   **5.10:1** on `#F2FBFD` and `#155E75` gives **6.92:1**, so accessible light-mode accents exist
   in the ramp already and no new hue is needed.
6. **The canvas is themed through the same tokens.** `<SunilPresence />` reads
   `--sunil-presence-*` at mount and on theme change (`SUNIL_PRESENCE_SPEC.md` §7.4). It does not
   hard-code `rgba(34,211,238,…)` the way the prototype does, so it re-themes with everything else.
7. **The contrast audit is re-run per theme.** §5 is a method, not a one-off result. A light theme
   is not accepted until its own version of the §5.3 table exists with computed ratios.
8. **What must *not* be done:** adding `@media (prefers-color-scheme: light)` overrides scattered
   through component files. Theme lives in one file, at one layer. A single stray component-level
   override is what turns "add a theme" into a rewrite.

---

## 9. Handover checklist for the Frontend Engineer

- [ ] `tokens.css` contains §2–§4 verbatim; `tokens.ts` mirrors it; both exported from `packages/ui`.
- [ ] No hex, `rgb()` or `rgba()` literal exists anywhere in `apps/web` (lint rule; FR-100).
- [ ] No `--sunil-*-a**` alpha token is used as a `color`.
- [ ] `--sunil-border-subtle` / `--sunil-border-rule` never appear on a focusable element.
- [ ] Fonts self-hosted, preloaded, metric-matched fallbacks generated (not hand-typed); font CLS = 0.00.
- [ ] `color-scheme: dark` set on `:root`; no light-mode flash on first paint (FR-103).
- [ ] Reduced-motion block from §3.3 present in the global stylesheet.
- [ ] The automated a11y scan (BL-806) asserts the §5.3 ratios against the *rendered* DOM, not
      against this document — if the two disagree, the DOM is right and this document is a defect.

---

## 10. Open items for the Delivery Manager

| # | Item | Recommendation |
|---|---|---|
| T-1 | D-1 changes the look of every small label in the product. It is the only change a human would notice. | Show the owner §6.1 before build. It is a genuine aesthetic cost and the human should own the decision, not inherit it. |
| T-2 | The prototype's `.greeting` sits over the live canvas. Rule §5.4.3 requires a scrim there. | Accept the scrim; it is a 0.82-alpha near-black wash that the vignette already implies. |
| T-3 | These tokens are reviewed by someone other than their author before BL-502 starts. | Per role boundary, I must not approve my own work. Route to the QA engineer for the a11y scan and to the Solution Architect for the `packages/ui` export shape. |
