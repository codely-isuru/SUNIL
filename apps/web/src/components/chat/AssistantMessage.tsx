"use client";

import { MarkdownBody } from "./markdown";
import { TraceDisclosure } from "./TraceDisclosure";
import type { TraceStep } from "./types";

export interface AssistantMessageProps {
  content: string;
  timestamp: string;
  trace: TraceStep[];
  expanded: boolean;
  onToggleTrace: () => void;
}

/**
 * A completed assistant turn (M1_CHAT_SPEC.md §5.2). Left-aligned, prefixed
 * with a small static SUNIL mark — the animated canvas scene is reserved
 * for the M8 ambient dashboard moment, never spent behind reading-heavy
 * chat (DESIGN_SYSTEM.md §0).
 */
export function AssistantMessage({
  content,
  timestamp,
  trace,
  expanded,
  onToggleTrace,
}: AssistantMessageProps) {
  return (
    <div className="flex items-start gap-3">
      <span
        aria-hidden="true"
        className="mt-1 inline-block h-5 w-5 shrink-0 rounded-full border-2 border-accent shadow-glow-hover"
      />
      <div className="flex max-w-[88%] flex-1 flex-col gap-2 sm:max-w-2xl">
        <div className="rounded-md bg-surface p-4">
          <MarkdownBody content={content} />
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-mono-body text-small text-text-muted">{timestamp}</span>
          <span aria-hidden="true" className="text-text-muted">
            ·
          </span>
          <TraceDisclosure steps={trace} expanded={expanded} onToggle={onToggleTrace} />
        </div>
      </div>
    </div>
  );
}
