import type { Config } from "tailwindcss";

// SUNIL design-system token contract — docs/design/DESIGN_SYSTEM.md
//
// §1 Colour tokens, radii, elevation (glow) and motion durations are pasted
// verbatim from DESIGN_SYSTEM.md §1's `theme.extend` code block.
//
// §2 Typography defines font stacks and a type scale but does not hand
// down a ready-made Tailwind snippet the way §1 does. `fontFamily`,
// `fontSize` and `letterSpacing` below are this engineer's translation of
// that scale into Tailwind tokens (flagged to the Architect/Designer as a
// judgement call — see the T14 report). Font weights use Tailwind's
// existing `font-normal/semibold/bold/extrabold` utilities directly
// (400/600/700/800), so no custom weight scale was added.
const config: Config = {
  content: [
    "./src/app/**/*.{ts,tsx}",
    "./src/components/**/*.{ts,tsx}",
    "./src/lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#030712",
        surface: { DEFAULT: "#0B1220", raised: "#111B2E" },
        border: {
          DEFAULT: "#1E2A3E",
          accent: "rgba(34,211,238,.18)",
          strong: "rgba(34,211,238,.4)",
        },
        accent: {
          DEFAULT: "#22D3EE",
          hover: "#67E8F9",
          active: "#06B6D4",
          on: "#031015",
        },
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

      // --- Typography (§2) — this engineer's Tailwind translation ---
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
      // [fontSize, lineHeight] rem pairs per DESIGN_SYSTEM.md §2's scale table.
      // Weight, letter-spacing and text-transform (uppercase) are applied as
      // ordinary Tailwind utilities (font-bold, tracking-h1, uppercase) at the
      // call site rather than baked into the size token.
      fontSize: {
        display: ["2.125rem", "1.1"], // 34px / 1.1
        h1: ["1.5rem", "1.3"], // 24px / 1.3
        h2: ["0.75rem", "1.4"], // 12px / 1.4
        h3: ["0.8125rem", "1.4"], // 13px / 1.4
        body: ["0.9375rem", "1.6"], // 15px / 1.6
        small: ["0.75rem", "1.5"], // 12px / 1.5
        micro: ["0.625rem", "1.4"], // 10px / 1.4
        code: ["0.875rem", "1.5"], // 14px / 1.5
      },
      letterSpacing: {
        display: "0.3em",
        h1: "0.15em",
        h2: "0.2em",
        h3: "0.05em",
        small: "0.02em",
        micro: "0.15em",
      },

      // --- Motion (§6) ---
      transitionTimingFunction: {
        standard: "cubic-bezier(0.4,0,0.2,1)",
      },
      keyframes: {
        "work-pulse": {
          "0%, 100%": { boxShadow: "0 0 24px rgba(34,211,238,.35)" },
          "50%": { boxShadow: "0 0 44px rgba(34,211,238,.55)" },
        },
      },
      animation: {
        // The WorkIndicator's breathing glow only — disabled under
        // prefers-reduced-motion in globals.css (§7 accessibility floor).
        "work-pulse": "work-pulse 1100ms cubic-bezier(0.4,0,0.2,1) infinite",
      },
    },
  },
  plugins: [],
};

export default config;
