/**
 * GATE 2 ENFORCEMENT — `rgba()` may never be a text `color`.
 *
 * This is the structural check that replaces a CSS linter (none is installed, and installing
 * one mid-wave is not permitted). It does two things:
 *
 *   1. POSITIVE CONTROLS — deliberate violations, asserted to be REJECTED. A checker that has
 *      never rejected anything is a checker nobody has tested. These fixtures are the same
 *      violations T1 wrote by hand to prove its import fences, kept permanently in the suite
 *      instead of being written, run once and deleted.
 *   2. THE REAL SCAN — every stylesheet in `packages/ui` and `apps/web`, with every `color:`
 *      and every text token resolved through the token graph in `tokens.css`, asserted clean.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  findTextColorAlphaViolations,
  hasAlpha,
  parseCssVariables,
  resolveCssValue,
} from "../tokens/css-contract.js";

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
  throw new Error("Could not locate the workspace root from " + process.cwd());
}

function collectCss(dir: string, found: string[] = []): string[] {
  let entries: string[];
  try {
    entries = readdirSync(dir);
  } catch {
    return found;
  }
  for (const entry of entries) {
    if (entry === "node_modules" || entry === "dist" || entry === ".next") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) collectCss(full, found);
    else if (entry.endsWith(".css")) found.push(full);
  }
  return found;
}

const ROOT = repoRoot();
const TOKENS_CSS = readFileSync(join(ROOT, "packages/ui/src/tokens/tokens.css"), "utf8");
const TOKEN_VARS = parseCssVariables(TOKENS_CSS);

describe("the checker rejects what it is supposed to reject (positive controls)", () => {
  it("detects alpha in every notation a stylesheet could use", () => {
    expect(hasAlpha("rgba(34, 211, 238, 0.55)")).toBe(true);
    expect(hasAlpha("hsla(190, 80%, 50%, 0.4)")).toBe(true);
    expect(hasAlpha("rgb(34 211 238 / 55%)")).toBe(true);
    expect(hasAlpha("#22d3ee88")).toBe(true);
    expect(hasAlpha("#22d3ee8")).toBe(false); // not a valid colour length
    expect(hasAlpha("transparent")).toBe(true);

    expect(hasAlpha("#22d3ee")).toBe(false);
    expect(hasAlpha("#22d3eeff")).toBe(false);
    expect(hasAlpha("rgb(34, 211, 238)")).toBe(false);
    expect(hasAlpha("rgba(34, 211, 238, 1)")).toBe(false);
  });

  it("follows the token graph before judging", () => {
    // `--sunil-accent-glow` → `--sunil-cyan-a55` → rgba(...). Three hops, one verdict.
    expect(resolveCssValue("var(--sunil-accent-glow)", TOKEN_VARS)).toBe(
      "rgba(34, 211, 238, 0.55)",
    );
    expect(resolveCssValue("var(--sunil-text-primary)", TOKEN_VARS)).toBe("#e3f5fa");
  });

  it("REJECTS the exact regression Gate 2 bans: the prototype's dim-cyan label colour", () => {
    const violating = `.subtitle { color: rgba(34, 211, 238, 0.55); }`;
    const violations = findTextColorAlphaViolations(violating, TOKEN_VARS, "fixture.css");
    expect(violations).toHaveLength(1);
    expect(violations[0]?.property).toBe("color");
    expect(violations[0]?.reason).toContain("Gate 2 bans rgba()");
  });

  it("REJECTS an alpha token reached through a var() chain", () => {
    // The subtle version: nothing here *looks* transparent.
    const violating = `.state { color: var(--sunil-accent-glow); }`;
    const violations = findTextColorAlphaViolations(violating, TOKEN_VARS, "fixture.css");
    expect(violations).toHaveLength(1);
    expect(violations[0]?.resolved).toBe("rgba(34, 211, 238, 0.55)");
  });

  it("REJECTS a text TOKEN defined with alpha, at its point of definition", () => {
    const violating = `:root { --sunil-text-muted: rgba(34,211,238,.55); --sunil-nav-item-fg: rgba(0,0,0,.5); }`;
    const vars = new Map([...TOKEN_VARS, ...parseCssVariables(violating)]);
    const violations = findTextColorAlphaViolations(violating, vars, "fixture.css");
    expect(violations.map((v) => v.property)).toEqual([
      "--sunil-text-muted",
      "--sunil-nav-item-fg",
    ]);
  });

  it("REJECTS a text colour that points at a token nobody defined", () => {
    const violating = `.x { color: var(--sunil-text-does-not-exist); }`;
    const violations = findTextColorAlphaViolations(violating, TOKEN_VARS, "fixture.css");
    expect(violations).toHaveLength(1);
    expect(violations[0]?.reason).toContain("not defined in the token graph");
  });

  it("ACCEPTS alpha where it is legitimate: glow, fill, stroke and borders", () => {
    const legitimate = `
      .panel { border: 1px solid var(--sunil-border-subtle); background: var(--sunil-surface); }
      .brand { box-shadow: var(--sunil-glow-xs) var(--sunil-accent-glow); }
      .label { color: var(--sunil-text-muted); }
      .inherit { color: inherit; }
    `;
    expect(findTextColorAlphaViolations(legitimate, TOKEN_VARS, "fixture.css")).toEqual([]);
  });
});

describe("the real scan — every stylesheet in packages/ui and apps/web", () => {
  const files = [
    ...collectCss(join(ROOT, "packages/ui/src")),
    ...collectCss(join(ROOT, "apps/web/src")),
  ];

  it("finds stylesheets to check (a scan of zero files proves nothing)", () => {
    expect(files.length).toBeGreaterThan(0);
  });

  it("contains no text colour carrying alpha, anywhere", () => {
    const violations = files.flatMap((file) => {
      const css = readFileSync(file, "utf8");
      const vars = new Map([...TOKEN_VARS, ...parseCssVariables(css)]);
      return findTextColorAlphaViolations(css, vars, relative(ROOT, file).replace(/\\/g, "/"));
    });
    expect(violations.map((v) => v.reason)).toEqual([]);
  });
});

describe("the text tokens themselves (DESIGN_TOKENS.md §5.3)", () => {
  const textTokens = [...TOKEN_VARS.keys()].filter((name) => name.startsWith("--sunil-text-"));

  it("defines every text role the semantic layer promises", () => {
    expect(textTokens).toEqual(
      expect.arrayContaining([
        "--sunil-text-primary",
        "--sunil-text-secondary",
        "--sunil-text-muted",
        "--sunil-text-accent",
        "--sunil-text-heading",
        "--sunil-text-emphasis",
        "--sunil-text-disabled",
        "--sunil-text-placeholder",
        "--sunil-text-on-accent",
      ]),
    );
  });

  it("resolves every one of them to an opaque colour", () => {
    for (const token of textTokens) {
      const resolved = resolveCssValue(`var(${token})`, TOKEN_VARS);
      expect(`${token} → ${resolved} (alpha: ${String(hasAlpha(resolved))})`).toBe(
        `${token} → ${resolved} (alpha: false)`,
      );
    }
  });

  it("keeps the Gate 2 correction: --sunil-text-muted is the OPAQUE #1BA3BC", () => {
    expect(resolveCssValue("var(--sunil-text-muted)", TOKEN_VARS)).toBe("#1ba3bc");
  });
});
