import type { Config } from "tailwindcss";

/**
 * SUNIL V2 token contract — `docs/design/DESIGN_SYSTEM.md` **Amendment A**
 * ("Obsidian & Gold", round 3), which is binding for every surface inside the
 * V2 shell.
 *
 * `colors`, `fontFamily`, `backgroundImage`, `boxShadow`, `keyframes` and
 * `animation` below are pasted **verbatim** from Amendment A §A.8. Do not
 * re-tune a value here: the amendment is the source of truth and every pair
 * ships with a computed contrast ratio (§A.7).
 *
 * `fontSize`, `letterSpacing`, `borderRadius` and `spacing` additions are this
 * engineer's translation of §A.5's type scale and §A.6's density rules into
 * Tailwind tokens (§A.5 gives a table, not a config block) — flagged in
 * `docs/tasks/S-D-web.md`.
 */
const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // ── Amendment A §A.8, verbatim ───────────────────────────────────────
      colors: {
        canvas: "#0B0906",
        surface: { DEFAULT: "#16120C", raised: "#201A11", high: "#2B2315" },
        border: {
          DEFAULT: "#282013",
          accent: "rgba(201,162,39,.16)",
          strong: "rgba(201,162,39,.38)",
        },
        accent: { DEFAULT: "#C9A227", hover: "#DBBE7F", active: "#A6801F", on: "#14100A" },
        gold: { deep: "#B08A2A" },
        text: {
          primary: "#CEC5B4",
          secondary: "#C4B48D",
          muted: "#9A8D71",
          disabled: "#59503C",
        },
        status: {
          pending: "#D98E4A",
          approved: "#5E96E0",
          consumed: "#3FAE6C",
          refused: "#E8685C",
          expired: "#9A8D71",
        },
        success: "#3FAE6C",
        warning: "#D98E4A",
        danger: { DEFAULT: "#E8685C", strong: "#E5484D" },
      },
      fontFamily: {
        display: ["var(--font-display)", "ui-sans-serif", "system-ui", "sans-serif"],
        body: ["var(--font-body)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
      backgroundImage: {
        // atmosphere (§A.4): panel top-light + metallic overlay for gold fills
        "sheen-panel": "linear-gradient(180deg, rgba(201,162,39,.03), rgba(201,162,39,0) 46%)",
        "sheen-metal":
          "linear-gradient(180deg, rgba(255,255,255,.14), rgba(255,255,255,0) 45%, rgba(0,0,0,.12))",
        "scanline":
          "repeating-linear-gradient(0deg, rgba(201,162,39,.012) 0 1px, transparent 1px 3px)",
      },
      boxShadow: {
        "glow-armed": "0 0 0 1px rgba(201,162,39,.55), 0 0 18px rgba(201,162,39,.30)",
        "glow-armed-danger": "0 0 0 1px rgba(232,104,92,.55), 0 0 18px rgba(232,104,92,.22)",
        "glow-focus": "0 0 0 4px rgba(201,162,39,.22)",
      },
      keyframes: {
        "work-pulse": {
          "0%, 100%": {
            boxShadow: "0 0 0 1px rgba(201,162,39,.42), 0 0 14px rgba(201,162,39,.20)",
          },
          "50%": {
            boxShadow: "0 0 0 1px rgba(201,162,39,.58), 0 0 26px rgba(201,162,39,.32)",
          },
        },
        shimmer: { "0%": { left: "-60%" }, "60%, 100%": { left: "115%" } },
        spin: { to: { transform: "rotate(360deg)" } },
      },
      animation: {
        // round 3: the live pulse breathes at 2600ms (1100ms read as urgency)
        "work-pulse": "work-pulse 2600ms cubic-bezier(0.4,0,0.2,1) infinite",
        shimmer: "shimmer 2600ms cubic-bezier(0.4,0,0.2,1) infinite",
        "spin-sm": "spin 900ms linear infinite",
      },

      // ── §A.5 type scale, translated to Tailwind tokens ───────────────────
      fontSize: {
        display: ["1.375rem", "1.2"], // 22px/1.2 — view H1, wordmark
        h2: ["0.75rem", "1.4"], // 12px/1.4 — section + panel headings
        body: ["0.875rem", "1.55"], // 14px/1.55 — default UI text
        cell: ["0.8125rem", "1.5"], // 13px/1.5 — dense list rows
        small: ["0.75rem", "1.5"], // 12px/1.5 — captions, helper lines
        micro: ["0.625rem", "1.4"], // 10px/1.4 — column headers, pills
        data: ["0.75rem", "1.5"], // 12px/1.5 — ids, offsets, countdowns
        untrusted: ["0.8125rem", "1.6"], // 13px — the quotation block
        stat: ["1.25rem", "1.2"], // 20px/1.2 — summary-rail figures
        key: ["1.625rem", "1"], // the dashboard hero's one gold figure
      },
      letterSpacing: {
        display: "0.08em",
        h2: "0.18em",
        micro: "0.12em",
        pill: "0.1em",
        stat: "0.02em",
        brand: "0.24em",
      },
      borderRadius: { sm: "3px", md: "6px", lg: "10px", full: "9999px" },
      transitionTimingFunction: { standard: "cubic-bezier(0.4,0,0.2,1)" },
    },
  },
  plugins: [],
};

export default config;
