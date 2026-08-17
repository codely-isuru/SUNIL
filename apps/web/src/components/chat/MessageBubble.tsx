export interface MessageBubbleProps {
  content: string;
  timestamp: string;
}

/**
 * The user's own message (M1_CHAT_SPEC.md §5.1). Right-aligned, a *light*
 * accent tint (never a full-strength accent fill under body text — see
 * DESIGN_SYSTEM.md §1's contrast note) so `text-primary` stays legible.
 * Timestamp reveals on hover on desktop; always visible on mobile, since
 * opacity (not `display`/`visibility`) is used, it stays in the
 * accessibility tree for screen-reader/keyboard users regardless.
 */
export function MessageBubble({ content, timestamp }: MessageBubbleProps) {
  return (
    <div className="group flex flex-col items-end gap-1">
      <div className="max-w-[88%] whitespace-pre-wrap rounded-md bg-accent/12 p-3 font-mono-body text-body text-text-primary sm:max-w-md">
        {content}
      </div>
      <span className="font-mono-body text-small text-text-muted opacity-100 transition-opacity duration-fast ease-standard sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100">
        {timestamp}
      </span>
    </div>
  );
}
