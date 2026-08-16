"use client";

import type { TraceStep } from "./types";

export interface TraceDisclosureProps {
  steps: TraceStep[];
  expanded: boolean;
  onToggle: () => void;
}

/**
 * "View reasoning steps ⌄" — collapsed by default, renders the plain-English
 * 12-line trace (M1_CHAT_SPEC.md §5.5) on demand, never raw JSON/log lines.
 * The toggle is a real `<button aria-expanded>`, not a bare `<div onClick>`
 * (§8) — Enter/Space work natively.
 */
export function TraceDisclosure({ steps, expanded, onToggle }: TraceDisclosureProps) {
  return (
    <div>
      <button
        type="button"
        aria-expanded={expanded}
        onClick={onToggle}
        className="inline-flex min-h-11 items-center gap-1 font-mono-body text-small text-text-muted underline decoration-dotted underline-offset-2 transition-colors duration-fast ease-standard hover:text-text-secondary"
      >
        View reasoning steps
        <span
          aria-hidden="true"
          className={`inline-block transition-transform duration-fast ease-standard ${expanded ? "rotate-180" : ""}`}
        >
          ⌄
        </span>
      </button>

      {expanded && (
        <ol className="mt-2 space-y-1 border-l border-border pl-4">
          {steps.map((step, index) => (
            <li
              key={`${index}-${step.label}`}
              className="flex items-baseline justify-between gap-4 font-mono-body text-small text-text-secondary"
            >
              <span>{step.label}</span>
              <span className="shrink-0 text-text-muted">{step.offset}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
