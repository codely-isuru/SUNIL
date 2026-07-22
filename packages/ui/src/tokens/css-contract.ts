/**
 * The structural enforcement of the Gate 2 colour rules.
 *
 * GATE 2 (human-approved, binding): **`rgba()` is BANNED as a text `color`.** A transparent
 * colour has no fixed contrast ratio — it only has one once you know what is painted behind
 * it, and nothing in a build can catch a regression of that. Opaque text tokens, always.
 *
 * ESLint cannot see inside a stylesheet and no CSS linter is installed (and installing one is
 * not permitted mid-wave), so the ban is enforced structurally instead: these pure functions
 * resolve every `color:` declaration and every text-carrying custom property through the token
 * graph in `tokens.css`, and `__tests__/css-contract.test.ts` runs them over every stylesheet
 * in `packages/ui` and `apps/web` and fails on any hit.
 *
 * Pure string functions only — no `node:fs`, no DOM. The test supplies the file contents, so
 * this module stays safe to include in a client bundle and is trivially testable with fixtures.
 */

/** A resolved token graph: custom-property name → its declared (unresolved) value. */
export type CssVariableMap = ReadonlyMap<string, string>;

export interface CssContractViolation {
  /** Where it was found, e.g. `packages/ui/src/styles/base.css`. */
  readonly file: string;
  /** 1-based line number of the offending declaration. */
  readonly line: number;
  /** The property that would paint text, e.g. `color` or `--sunil-nav-item-fg`. */
  readonly property: string;
  /** The declared value, e.g. `var(--sunil-accent-glow)`. */
  readonly declared: string;
  /** What the value resolves to after following the token graph. */
  readonly resolved: string;
  /** Human-readable explanation, used directly as the assertion message. */
  readonly reason: string;
}

/**
 * A declaration is `name: value`, where `name` begins immediately after the start of the file
 * or after a `;`, `{` or `}`. The lookbehind is zero-width on purpose: a consuming prefix
 * would swallow the separator and silently skip every second declaration.
 */
const DECLARATION_RE = /(?<=^|[;{}])\s*(--[\w-]+|[a-zA-Z-]+)\s*:\s*([^;{}]+)/g;
const VAR_CALL_RE = /var\(\s*(--[\w-]+)\s*(?:,\s*([^()]*(?:\([^()]*\)[^()]*)*))?\)/;

/**
 * Properties that paint text. `color` is the CSS property; the custom-property patterns are
 * the token layer's own text roles, checked at their point of DEFINITION so a bad token is
 * caught once rather than at every use site.
 */
const TEXT_PROPERTIES = new Set(["color", "-webkit-text-fill-color"]);
const TEXT_TOKEN_PATTERNS: readonly RegExp[] = [
  /^--sunil-text-/,
  /-fg$/,
  /-fg-(hover|active|disabled)$/,
  /^--sunil-.*-title-fg$/,
];

/** Values that are legal in a text-colour position without being a colour at all. */
const NON_COLOUR_KEYWORDS = new Set(["inherit", "initial", "unset", "revert", "currentcolor"]);

/**
 * Blank out block comments while preserving length and newlines, so a colon inside a comment
 * cannot be mistaken for a declaration and reported line numbers stay correct.
 */
export function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, (block) => block.replace(/[^\n]/g, " "));
}

/** Parse every custom-property declaration in a stylesheet into a token map. */
export function parseCssVariables(css: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const match of stripComments(css).matchAll(DECLARATION_RE)) {
    const property = match[1];
    const value = match[2];
    if (property?.startsWith("--") && value !== undefined) {
      map.set(property, value.trim());
    }
  }
  return map;
}

/**
 * Follow `var()` references through the token graph until a literal value is reached.
 * Returns the input unchanged if it contains no `var()`; returns `"<unresolved:--x>"` for a
 * reference with no definition and no fallback, which the caller treats as a violation.
 */
export function resolveCssValue(value: string, vars: CssVariableMap, depth = 0): string {
  if (depth > 12) return value;
  const match = VAR_CALL_RE.exec(value);
  if (!match) return value.trim();

  const [whole, name, fallback] = match;
  const target = name === undefined ? undefined : vars.get(name);
  let replacement: string;
  if (target !== undefined) {
    replacement = target;
  } else if (fallback !== undefined) {
    replacement = fallback;
  } else {
    replacement = `<unresolved:${name ?? "?"}>`;
  }
  return resolveCssValue(value.replace(whole, replacement), vars, depth + 1);
}

/**
 * Does this literal colour value carry transparency?
 * Covers `rgba()`, `hsla()`, modern `rgb(… / α)`, 4- and 8-digit hex, and `transparent`.
 */
export function hasAlpha(value: string): boolean {
  const v = value.trim().toLowerCase();
  if (v === "transparent") return true;

  const functional = /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(([^)]*)\)/.exec(v);
  if (functional?.[1] !== undefined) {
    const args = functional[1];
    if (args.includes("/")) {
      const alpha = args.split("/")[1]?.trim();
      if (alpha !== undefined && alpha !== "" && alpha !== "1" && alpha !== "100%") return true;
    }
    const parts = args.split(",").map((p) => p.trim());
    if (parts.length === 4) {
      const alpha = parts[3];
      if (alpha !== undefined && alpha !== "1" && alpha !== "100%") return true;
    }
  }

  const hex = /^#([0-9a-f]{3,8})$/.exec(v);
  if (hex?.[1] !== undefined) {
    const digits = hex[1];
    if (digits.length === 4) return digits[3] !== "f";
    if (digits.length === 8) return digits.slice(6) !== "ff";
  }
  return false;
}

function isTextProperty(property: string): boolean {
  if (TEXT_PROPERTIES.has(property.toLowerCase())) return true;
  return property.startsWith("--") && TEXT_TOKEN_PATTERNS.some((re) => re.test(property));
}

function lineOf(css: string, index: number): number {
  let line = 1;
  for (let i = 0; i < index && i < css.length; i += 1) {
    if (css[i] === "\n") line += 1;
  }
  return line;
}

/**
 * The check itself. Scans one stylesheet for text colours that carry alpha, resolving token
 * references through `vars` (normally the map parsed from `tokens.css` merged with the file's
 * own declarations).
 */
export function findTextColorAlphaViolations(
  css: string,
  vars: CssVariableMap,
  file: string,
): CssContractViolation[] {
  const violations: CssContractViolation[] = [];

  const source = stripComments(css);
  for (const match of source.matchAll(DECLARATION_RE)) {
    const property = match[1];
    const declared = match[2]?.trim();
    if (property === undefined || declared === undefined) continue;
    if (!isTextProperty(property)) continue;

    const bare = declared.replace(/\s*!important$/, "").trim();
    if (NON_COLOUR_KEYWORDS.has(bare.toLowerCase())) continue;

    const resolved = resolveCssValue(bare, vars);
    if (resolved.startsWith("<unresolved:")) {
      violations.push({
        file,
        line: lineOf(source, match.index ?? 0),
        property,
        declared: bare,
        resolved,
        reason: `${file}: \`${property}: ${bare}\` references a custom property that is not defined in the token graph, so its contrast ratio cannot be verified.`,
      });
      continue;
    }

    if (hasAlpha(resolved)) {
      violations.push({
        file,
        line: lineOf(source, match.index ?? 0),
        property,
        declared: bare,
        resolved,
        reason: `${file}: \`${property}: ${bare}\` resolves to \`${resolved}\`, which carries alpha. Gate 2 bans rgba() as a text colour — a transparent colour has no fixed contrast ratio. Use an opaque --sunil-text-* token.`,
      });
    }
  }

  return violations;
}
