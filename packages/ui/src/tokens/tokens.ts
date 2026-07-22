/**
 * Typed mirror of `tokens.css` (DESIGN_TOKENS.md §1).
 *
 * This exists because `<SunilPresence />` draws to a canvas and cannot read CSS variables at
 * paint time without a `getComputedStyle` call. Per SUNIL_PRESENCE_SPEC.md §7.4 the component
 * reads the CSS variables once per mount / theme change and caches them; the values here are
 * the typed FALLBACK and the test fixture — not a second source of truth.
 *
 * `tokens.css` is authoritative. `__tests__/tokens.test.ts` asserts the two agree, so a value
 * changed in one file and not the other is a failing test rather than a silent drift.
 */

/** Every SUNIL custom property is namespaced with this prefix (mirrors `@sunil/core/tokens`). */
export const SUNIL_TOKEN_PREFIX = "--sunil-" as const;

/**
 * The colour tokens `<SunilPresence />` resolves at runtime.
 * Values are the dark-theme resolution of `--sunil-presence-*` in `tokens.css`.
 */
export const PRESENCE_COLOR_FALLBACKS = {
  point: "#67e8f9",
  arc: "#22d3ee",
  marker: "#a5f3fc",
  glow: "#22d3ee",
} as const;

export type PresenceColorRole = keyof typeof PRESENCE_COLOR_FALLBACKS;

/** CSS custom-property names for the presence colours, in resolution order. */
export const PRESENCE_COLOR_VARS: Readonly<Record<PresenceColorRole, string>> = {
  point: "--sunil-presence-point",
  arc: "--sunil-presence-arc",
  marker: "--sunil-presence-marker",
  glow: "--sunil-presence-glow",
};

/** Named presence box sizes, mirroring `--sunil-presence-size-*` (SUNIL_PRESENCE_SPEC.md §7.3). */
export const PRESENCE_SIZES = {
  sm: 200,
  md: 320,
  lg: 440,
} as const;

export type PresenceSizeName = keyof typeof PRESENCE_SIZES;

/**
 * The brand colours locked by `SUNIL_ARCHITECTURE.md` §3 and asserted by FR-100.
 * Nothing else in the codebase may hold these literals.
 */
export const BRAND_COLORS = {
  cyan: "#22d3ee",
  bg: "#030712",
  panel: "rgba(7, 16, 32, 0.72)",
  amber: "#fbbf24",
  ok: "#34d399",
} as const;

/**
 * Text colour tokens and their resolved OPAQUE values.
 *
 * Gate 2: `rgba()` is banned as a text colour — a transparent colour has no fixed contrast
 * ratio. Every value here is opaque, and `css-contract.ts` proves it stays that way.
 * Ratios are the worst case from the DESIGN_TOKENS.md §5.3 audit (over the speaking glow).
 */
export const TEXT_COLORS = {
  "--sunil-text-primary": { value: "#e3f5fa", worstRatio: 12.46 },
  "--sunil-text-secondary": { value: "#9ac5d4", worstRatio: 7.54 },
  "--sunil-text-muted": { value: "#1ba3bc", worstRatio: 4.67 },
  "--sunil-text-accent": { value: "#22d3ee", worstRatio: 7.74 },
  "--sunil-text-heading": { value: "#7dd3fc", worstRatio: 8.39 },
  "--sunil-text-emphasis": { value: "#a5f3fc", worstRatio: 11.21 },
  "--sunil-text-disabled": { value: "#6499ae", worstRatio: 6.19 },
  "--sunil-text-placeholder": { value: "#6499ae", worstRatio: 6.19 },
  "--sunil-text-on-accent": { value: "#030712", worstRatio: 11.14 },
} as const satisfies Readonly<Record<string, { value: string; worstRatio: number }>>;

export type TextColorToken = keyof typeof TEXT_COLORS;

/** Motion durations in milliseconds, mirroring `--sunil-duration-*`. */
export const DURATIONS = {
  instant: 75,
  fast: 120,
  base: 180,
  slow: 250,
  slower: 400,
  pulse: 1100,
} as const;

/** Breakpoint minimum widths in CSS pixels (PORTAL_SHELL_SPEC.md §2.1). */
export const BREAKPOINTS = {
  sm: 480,
  md: 768,
  lg: 1024,
  xl: 1280,
  "2xl": 1536,
} as const;

export type BreakpointName = keyof typeof BREAKPOINTS;

/** The state-change cross-fade in SUNIL_PRESENCE_SPEC.md §4.1, in milliseconds. */
export const PRESENCE_STATE_CROSSFADE_MS = 400;
