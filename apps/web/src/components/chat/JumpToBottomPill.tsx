"use client";

export interface JumpToBottomPillProps {
  visible: boolean;
  onClick: () => void;
}

/**
 * Floating pill, bottom-centre above the composer — shown only once the
 * user has scrolled up during/after new content (M1_CHAT_SPEC.md §1.1/§7).
 */
export function JumpToBottomPill({ visible, onClick }: JumpToBottomPillProps) {
  if (!visible) return null;

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-4 flex justify-center">
      <button
        type="button"
        onClick={onClick}
        className="pointer-events-auto flex min-h-11 items-center gap-1.5 rounded-full border border-border-accent bg-surface px-4 py-2 font-mono-body text-small text-text-secondary shadow-glow-hover transition-colors duration-fast ease-standard hover:border-border-strong hover:text-text-primary"
      >
        <span aria-hidden="true">↓</span>
        New reply
      </button>
    </div>
  );
}
