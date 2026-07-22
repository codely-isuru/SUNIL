/**
 * Font loading — DESIGN_TOKENS.md §7.
 *
 * DECISION: self-host. The prototype's `<link href="https://fonts.googleapis.com/…">` cannot
 * ship, for three independent reasons, and none of them is negotiable:
 *   1. FR-031 / NFR-004 require a strict CSP. The CDN link needs `style-src
 *      fonts.googleapis.com` and `font-src fonts.gstatic.com`, weakening the policy for a
 *      decorative asset. `src/middleware.ts` therefore sends `font-src 'self'` and nothing else.
 *   2. Two extra DNS + TLS round trips before first text paint, against NFR-007's budget.
 *   3. Phase 1 is local-only (A-01) and must work on a machine with no route to Google.
 *
 * ───────────────────────────────────────────────────────────────────────────────────────────
 * OUTSTANDING — THE TWO FONT BINARIES ARE NOT IN THE REPOSITORY.
 *
 * `next/font/local` requires the actual `.woff2` files at build time, and this workspace has
 * no route to fetch them (and fabricating a stand-in face would be worse than shipping the
 * fallback: it would look wrong and nobody would know why). So the portal currently renders in
 * the §7.4 fallback stacks below, which are the same stacks the real faces sit in front of.
 * The layout is identical either way — that is exactly what the metric-matched fallback is
 * for — only the letterforms differ.
 *
 * TO COMPLETE (one commit, no code changes anywhere else):
 *   1. add `apps/web/public/fonts/orbitron-variable.woff2` (variable 400–900, latin subset)
 *      and `apps/web/public/fonts/share-tech-mono-400.woff2` (static 400, latin subset);
 *   2. replace the two constants below with the `localFont(...)` calls in the block comment;
 *   3. spread `orbitron.variable` and `shareTechMono.variable` onto `<html>` in `layout.tsx`
 *      and bind `--sunil-font-display` / `--sunil-font-mono` to them;
 *   4. re-measure CLS with the network throttled. §7.3 requires font-swap CLS of 0.00; if it
 *      is non-zero the overrides are wrong, not the strategy.
 *
 * `adjustFontFallback` is what generates the ascent/descent/line-gap/size-adjust overrides
 * from the real metrics at build time. Do NOT hand-tune those four percentages — §7.3 is
 * explicit that they are generated, never estimated, so they cannot drift when a file changes.
 *
 * ```ts
 * import localFont from "next/font/local";
 *
 * export const orbitron = localFont({
 *   src: "../../public/fonts/orbitron-variable.woff2",
 *   variable: "--sunil-font-display-loaded",
 *   display: "swap",
 *   preload: true,
 *   fallback: ["Trebuchet MS", "ui-sans-serif", "system-ui", "sans-serif"],
 *   adjustFontFallback: "Arial",
 * });
 *
 * export const shareTechMono = localFont({
 *   src: "../../public/fonts/share-tech-mono-400.woff2",
 *   variable: "--sunil-font-mono-loaded",
 *   display: "swap",
 *   preload: true,
 *   fallback: ["ui-monospace", "Cascadia Mono", "Consolas", "Courier New", "monospace"],
 *   adjustFontFallback: "Arial",
 * });
 * ```
 * ───────────────────────────────────────────────────────────────────────────────────────────
 */

/** True once the two `.woff2` files land in `public/fonts/` and the block above is enabled. */
export const SELF_HOSTED_FONTS_PRESENT = false;

/**
 * §7.4, authoritative. Windows 11 is the reference platform (NFR-017), so Consolas and
 * Cascadia Mono — present on every Windows 11 install — lead the mono fallback.
 * These strings are the values `--sunil-font-display` / `--sunil-font-mono` already hold in
 * `tokens.css`; they are restated here only so the handover above is self-contained.
 */
export const FONT_STACKS = {
  display:
    "'Orbitron', 'Orbitron Fallback', 'Trebuchet MS', ui-sans-serif, system-ui, sans-serif",
  mono: "'Share Tech Mono', 'Share Tech Mono Fallback', ui-monospace, 'Cascadia Mono', Consolas, 'Courier New', monospace",
} as const;
