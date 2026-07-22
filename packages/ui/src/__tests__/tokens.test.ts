/**
 * FR-100 — the tokens are a faithful extraction, and `tokens.ts` does not drift from
 * `tokens.css`. DESIGN_TOKENS.md §1: the CSS is authoritative and the TypeScript is the typed
 * fallback for the canvas plus the test fixture. Two files holding the same numbers is a
 * standing invitation to drift, so the agreement is asserted rather than trusted.
 */
import { readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { parseCssVariables, resolveCssValue } from "../tokens/css-contract.js";
import {
  BRAND_COLORS,
  BREAKPOINTS,
  DURATIONS,
  PRESENCE_COLOR_FALLBACKS,
  PRESENCE_COLOR_VARS,
  PRESENCE_SIZES,
  TEXT_COLORS,
} from "../tokens/tokens.js";

function repoRoot(): string {
  let dir = process.cwd();
  for (let i = 0; i < 8; i += 1) {
    try {
      statSync(join(dir, "pnpm-workspace.yaml"));
      return dir;
    } catch {
      dir = resolve(dir, "..");
    }
  }
  throw new Error("Could not locate the workspace root");
}

const CSS = readFileSync(join(repoRoot(), "packages/ui/src/tokens/tokens.css"), "utf8");
/** The default theme only: the reduced-motion block deliberately re-declares the durations. */
const BASE_CSS = CSS.split("@media (prefers-reduced-motion")[0] ?? CSS;
const VARS = parseCssVariables(BASE_CSS);
const resolved = (name: string): string => resolveCssValue(`var(${name})`, VARS).toLowerCase();

describe("FR-100 — the brand palette named in the requirement", () => {
  it("defines the locked colours from ARCHITECTURE §3", () => {
    expect(resolved("--sunil-cyan-400")).toBe(BRAND_COLORS.cyan);
    expect(resolved("--sunil-bg")).toBe(BRAND_COLORS.bg);
    expect(resolved("--sunil-surface")).toBe("rgba(7, 16, 32, 0.72)");
    expect(resolved("--sunil-amber-400")).toBe(BRAND_COLORS.amber);
    expect(resolved("--sunil-emerald-400")).toBe(BRAND_COLORS.ok);
  });

  it("defines the Orbitron / Share Tech Mono type roles", () => {
    expect(VARS.get("--sunil-font-display")).toContain("Orbitron");
    expect(VARS.get("--sunil-font-mono")).toContain("Share Tech Mono");
    for (const role of [
      "display-lg",
      "display",
      "display-sm",
      "title",
      "eyebrow",
      "action",
      "body",
      "body-sm",
      "caption",
      "micro",
    ]) {
      expect(VARS.has(`--sunil-type-${role}-size`)).toBe(true);
      expect(VARS.has(`--sunil-type-${role}-lh`)).toBe(true);
      expect(VARS.has(`--sunil-type-${role}-weight`)).toBe(true);
    }
  });

  it("defines the panel, lamp and spacing tokens", () => {
    expect(VARS.has("--sunil-panel-bg")).toBe(true);
    expect(VARS.get("--sunil-panel-accent-w")).toBe("46px"); // prototype `.panel::before`
    expect(VARS.get("--sunil-lamp-size")).toBe("8px");
    expect(VARS.get("--sunil-space-16")).toBe("16px");
    expect(VARS.get("--sunil-space-24")).toBe("24px");
  });

  it("carries the prototype's oddities verbatim — they ARE the HUD's fingerprint", () => {
    expect(VARS.get("--sunil-radius-6")).toBe("6px");
    expect(VARS.get("--sunil-panel-accent-inset")).toBe("var(--sunil-space-12)");
    expect(VARS.get("--sunil-panel-blur")).toBe("3px");
  });
});

describe("tokens.ts mirrors tokens.css", () => {
  it("agrees on every presence colour", () => {
    for (const [role, variable] of Object.entries(PRESENCE_COLOR_VARS)) {
      expect(resolved(variable)).toBe(
        PRESENCE_COLOR_FALLBACKS[role as keyof typeof PRESENCE_COLOR_FALLBACKS],
      );
    }
  });

  it("agrees on every presence size", () => {
    for (const [name, px] of Object.entries(PRESENCE_SIZES)) {
      expect(VARS.get(`--sunil-presence-size-${name}`)).toBe(`${px}px`);
    }
  });

  it("agrees on every text colour, and each one is opaque (Gate 2)", () => {
    for (const [token, spec] of Object.entries(TEXT_COLORS)) {
      expect(resolved(token)).toBe(spec.value);
      expect(spec.value).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("agrees on durations and breakpoints", () => {
    for (const [name, ms] of Object.entries(DURATIONS)) {
      expect(VARS.get(`--sunil-duration-${name}`)).toBe(`${ms}ms`);
    }
    for (const [name, px] of Object.entries(BREAKPOINTS)) {
      expect(VARS.get(`--sunil-bp-${name}`)).toBe(`${px}px`);
    }
  });
});

describe("the three-layer rule (DESIGN_TOKENS.md §3, §4)", () => {
  const componentPrefixes = [
    "--sunil-shell-",
    "--sunil-nav-",
    "--sunil-panel-",
    "--sunil-btn-",
    "--sunil-field-",
    "--sunil-lamp-",
    "--sunil-badge-",
    "--sunil-presence-",
    "--sunil-focus-",
  ];

  it("no component colour token points straight at a primitive", () => {
    const primitivePattern =
      /^var\(--sunil-(cyan|sky|ice|void|scrim|emerald|amber|rose|slate)-/;
    const offenders: string[] = [];
    for (const [name, value] of VARS) {
      if (!componentPrefixes.some((prefix) => name.startsWith(prefix))) continue;
      if (primitivePattern.test(value)) offenders.push(`${name}: ${value}`);
    }
    // Documented exceptions: `--sunil-badge-fg` and the presence colours are specified in
    // DESIGN_TOKENS.md §4 as direct primitive references.
    expect(offenders).toEqual([
      "--sunil-badge-fg: var(--sunil-ice-500)",
      "--sunil-presence-point: var(--sunil-cyan-300)",
      "--sunil-presence-arc: var(--sunil-cyan-400)",
      "--sunil-presence-marker: var(--sunil-cyan-200)",
      "--sunil-presence-glow: var(--sunil-cyan-400)",
    ]);
  });

  it("sets color-scheme: dark so native controls follow the theme (FR-103, §8.4)", () => {
    expect(CSS).toContain("color-scheme: dark");
  });

  it("collapses every motion duration under prefers-reduced-motion, but not to zero (§3.3)", () => {
    expect(CSS).toContain("@media (prefers-reduced-motion: reduce)");
    expect(CSS).toContain("--sunil-duration-slower: 0.01ms");
    // 0.01ms rather than 0 so transitionend/animationend still fire and no state machine stalls.
    expect(CSS).not.toContain("--sunil-duration-slower: 0;");
  });
});
