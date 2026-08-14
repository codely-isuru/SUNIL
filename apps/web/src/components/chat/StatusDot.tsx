"use client";

export type StatusDotState = "online" | "warn" | "offline";

export interface StatusDotProps {
  state: StatusDotState;
  label: string;
}

const DOT_COLOR: Record<StatusDotState, string> = {
  online: "bg-success shadow-[0_0_6px_theme(colors.success)]",
  warn: "bg-warning shadow-[0_0_6px_theme(colors.warning)]",
  offline: "bg-danger shadow-[0_0_6px_theme(colors.danger.DEFAULT)]",
};

/**
 * The prototype's "lamp" pattern: a coloured dot paired with a text label,
 * never colour alone (DESIGN_SYSTEM.md §7 — "colour is never the only signal").
 */
export function StatusDot({ state, label }: StatusDotProps) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        aria-hidden="true"
        className={`inline-block h-2 w-2 rounded-full ${DOT_COLOR[state]}`}
      />
      <span className="font-mono-ui text-micro uppercase tracking-micro text-text-secondary">
        {label}
      </span>
    </span>
  );
}
