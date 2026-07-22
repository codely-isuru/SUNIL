/**
 * Design-token *contract* — names and shapes only.
 *
 * The token VALUES live in `packages/ui` (owned by the frontend/UI-UX workstream,
 * extracted from the read-only `prototype/`). This module exists so `packages/ui` and
 * `apps/web` can share a typed vocabulary without importing server schemas: it is the
 * second of the two `@sunil/core` paths `packages/ui` may import (§3.2).
 *
 * NO runtime dependencies. NO Zod.
 */
/** Visual state of `<SunilPresence />` (FR-102). Defined here so `packages/ui` can reach it. */
export type PresenceState = "idle" | "thinking" | "speaking";

/** Every SUNIL CSS custom property is namespaced with this prefix. */
export const TOKEN_CSS_PREFIX = "--sunil-" as const;

/** Token categories the Phase 1 shell is expected to define (FR-100/103). */
export const TOKEN_CATEGORIES = [
  "color",
  "space",
  "font",
  "radius",
  "shadow",
  "motion",
  "z",
] as const;

export type TokenCategory = (typeof TOKEN_CATEGORIES)[number];

/** A flat map of fully-qualified token name → CSS value, e.g. `--sunil-color-bg`. */
export type DesignTokenMap = Readonly<Record<string, string>>;

/** Build a namespaced CSS custom-property name from a category and a leaf name. */
export function cssVarName(category: TokenCategory, name: string): string {
  return `${TOKEN_CSS_PREFIX}${category}-${name}`;
}

/** Reference a token in a CSS value position: `var(--sunil-color-bg)`. */
export function cssVar(category: TokenCategory, name: string): string {
  return `var(${cssVarName(category, name)})`;
}
