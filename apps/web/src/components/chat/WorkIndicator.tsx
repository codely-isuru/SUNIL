"use client";

import type { WorkPhase } from "./types";

export interface WorkIndicatorProps {
  phase: WorkPhase;
  /** The resolved project/tool name once the plan is known (§5.3) — undefined until then. */
  dynamicLabel?: string;
  elapsedSeconds: number;
  showReassurance: boolean;
  onCancel: () => void;
}

/**
 * Stage → phase copy (M1_CHAT_SPEC.md §5.3). The API sends stage enums only
 * (NFR-020's twelve names collapsed to these four by `lib/phases.ts`, T16) —
 * this component owns the human-readable label for each, the same way
 * `ErrorCard` owns its own copy per variant.
 */
function phaseLabel(phase: WorkPhase, dynamicLabel?: string): string {
  switch (phase) {
    case "understanding":
      return "Reading your request…";
    case "planning":
      return "Working out a plan…";
    case "working":
      return dynamicLabel ? `Checking ${dynamicLabel}…` : "Working on it…";
    case "finishing":
      return "Putting your answer together…";
  }
}

function formatElapsed(totalSeconds: number): string {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = Math.floor(safeSeconds / 60);
  const seconds = safeSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

/**
 * The core design problem the brief calls "the interesting part" (§5.3):
 * a turn can run up to 30s, and neither a bare spinner nor a raw 12-stage
 * log is acceptable. Four visible phases, one dynamic detail, an honest
 * elapsed counter, a reassurance line past 20s, and a Cancel control —
 * never a fake percentage bar.
 */
export function WorkIndicator({
  phase,
  dynamicLabel,
  elapsedSeconds,
  showReassurance,
  onCancel,
}: WorkIndicatorProps) {
  const label = phaseLabel(phase, dynamicLabel);

  return (
    <div className="flex items-start gap-3 rounded-md border border-border-accent bg-surface p-4 shadow-glow-active">
      <div className="flex flex-1 flex-col gap-2">
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            <span className="font-mono-body text-body text-text-secondary">{label}</span>
            <span aria-hidden="true" className="flex items-center gap-1">
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-work-pulse" />
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-work-pulse [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 rounded-full bg-accent animate-work-pulse [animation-delay:300ms]" />
            </span>
          </div>
          <button
            type="button"
            onClick={onCancel}
            className="min-h-11 rounded-md px-2 font-mono-body text-small text-danger underline decoration-dotted underline-offset-2 transition-colors duration-fast ease-standard hover:text-danger-strong"
          >
            Cancel
          </button>
        </div>

        <div className="flex items-center gap-3">
          <span className="font-mono-ui text-small text-text-muted">
            {formatElapsed(elapsedSeconds)}
          </span>
          {showReassurance && (
            <span className="font-mono-body text-small text-text-muted">
              Still working — larger checks can take a little longer.
            </span>
          )}
        </div>
      </div>

      {/* One aria-live update per phase change only — never per elapsed tick (§5.3, §8). */}
      <div aria-live="polite" className="sr-only">
        {label}
      </div>
    </div>
  );
}
