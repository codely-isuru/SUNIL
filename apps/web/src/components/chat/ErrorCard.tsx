"use client";

import type { ErrorVariant } from "./types";

export interface ErrorCardProps {
  variant: ErrorVariant;
  /** Formatted "{Project A}, {Project B}" list — `unknown_project` only (§5.9). */
  message?: string;
  onRetry?: () => void;
  onEdit?: () => void;
}

interface CopyBlock {
  text: string;
  action: "retry" | "edit";
}

/**
 * The four `ErrorCard` variants, keyed by `failure.kind` (§6's frozen
 * contract → `provider_error | tool_failed | plan_rejected | unknown_project`).
 * Copy is the Designer's final text, verbatim (§5.6–5.9) — never paraphrase
 * or invent copy here.
 */
function copyFor(variant: ErrorVariant, message?: string): CopyBlock {
  switch (variant) {
    case "generic":
      return {
        text: "Something went wrong on my end and I couldn't finish that.",
        action: "retry",
      };
    case "tool_failed":
      return {
        text: "I couldn't reach GitHub to check that just now. Try again in a moment.",
        action: "retry",
      };
    case "plan_rejected":
      return {
        text: "I wasn't able to work out a safe plan for that request. Could you rephrase it?",
        action: "edit",
      };
    case "unknown_project":
      return {
        text: `I don't recognise that project. Right now I only know about: ${message ?? ""}`,
        action: "edit",
      };
  }
}

export function ErrorCard({ variant, message, onRetry, onEdit }: ErrorCardProps) {
  const copy = copyFor(variant, message);

  return (
    <div
      role="alert"
      aria-live="assertive"
      className="flex items-start gap-3 rounded-md border border-danger bg-surface p-4"
    >
      <span aria-hidden="true" className="mt-0.5 text-danger">
        ⚠
      </span>
      <div className="flex flex-1 flex-col items-start gap-3">
        <p className="font-mono-body text-body text-text-primary">{copy.text}</p>
        {copy.action === "retry" ? (
          <button
            type="button"
            onClick={onRetry}
            className="min-h-11 rounded-md border border-danger px-4 py-2 font-mono-body text-small font-semibold text-danger transition-colors duration-fast ease-standard hover:bg-danger hover:text-accent-on"
          >
            Try again
          </button>
        ) : (
          <button
            type="button"
            onClick={onEdit}
            className="min-h-11 rounded-md border border-danger px-4 py-2 font-mono-body text-small font-semibold text-danger transition-colors duration-fast ease-standard hover:bg-danger hover:text-accent-on"
          >
            Edit message
          </button>
        )}
      </div>
    </div>
  );
}
