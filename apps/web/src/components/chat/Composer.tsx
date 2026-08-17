"use client";

import { useEffect, useRef, useSyncExternalStore } from "react";
import type { ChangeEvent, KeyboardEvent } from "react";

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onCancel: () => void;
  busy: boolean;
  maxRows?: number;
  /**
   * Bump this (e.g. a counter) to imperatively focus the textarea — used by
   * `SuggestionChips.onPick` ("populates the composer ... and focuses it",
   * §3) and `ErrorCard`'s `unknown_project`/`plan_rejected` "Edit message"
   * action (§5.8/§5.9), both from T16. A prop rather than a forwarded ref,
   * to keep this a plain props-driven component.
   */
  focusToken?: number;
}

const PLACEHOLDER = "Ask SUNIL to check on something…";

// Matches the same breakpoint M1_CHAT_SPEC.md §1.2 uses to switch to the
// mobile layout — Enter-to-send only applies at/above it. Below it, the
// Enter/return key always inserts a newline; only the Send button submits.
const DESKTOP_MEDIA_QUERY = "(min-width: 640px)";

function subscribeToViewport(callback: () => void) {
  const mql = window.matchMedia(DESKTOP_MEDIA_QUERY);
  mql.addEventListener("change", callback);
  return () => mql.removeEventListener("change", callback);
}

function getIsDesktopViewport() {
  return window.matchMedia(DESKTOP_MEDIA_QUERY).matches;
}

// Assume mobile (no Enter-to-send) until the client has actually measured
// the viewport — a false negative here is silent, a false positive would
// send a message the user didn't mean to (§1.2).
function getServerIsDesktopViewport() {
  return false;
}

/**
 * Drives the four composer states of M1_CHAT_SPEC.md §4. "Recovery" is not
 * a distinct prop here — it is just the Typing state with `value` still
 * holding the original text, which the caller (T16) is responsible for
 * re-populating after an error/cancel.
 */
export function Composer({
  value,
  onChange,
  onSend,
  onCancel,
  busy,
  maxRows = 6,
  focusToken,
}: ComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isDesktop = useSyncExternalStore(
    subscribeToViewport,
    getIsDesktopViewport,
    getServerIsDesktopViewport,
  );

  useEffect(() => {
    if (focusToken !== undefined) textareaRef.current?.focus();
  }, [focusToken]);

  // Auto-grow 1 → maxRows lines, then become internally scrollable.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    const lineHeightPx = parseFloat(getComputedStyle(el).lineHeight || "24");
    const maxHeightPx = lineHeightPx * maxRows;
    el.style.height = "auto";
    const nextHeight = Math.min(el.scrollHeight, maxHeightPx);
    el.style.height = `${nextHeight}px`;
    el.style.overflowY = el.scrollHeight > maxHeightPx ? "auto" : "hidden";
  }, [value, maxRows]);

  const canSend = value.trim().length > 0 && !busy;

  function handleChange(event: ChangeEvent<HTMLTextAreaElement>) {
    if (busy) return;
    onChange(event.target.value);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (busy || !isDesktop) return; // Enter-to-send is desktop-only (§1.2).
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSend) onSend();
    }
  }

  return (
    <div
      className="border-t border-border bg-surface p-4"
      style={{ paddingBottom: "max(1rem, env(safe-area-inset-bottom))" }}
    >
      <div className="mx-auto flex max-w-3xl items-end gap-3">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          readOnly={busy}
          placeholder={PLACEHOLDER}
          rows={1}
          aria-label="Message"
          className="flex-1 resize-none rounded-md border border-border bg-surface-raised px-3 py-2 font-mono-body text-body text-text-primary placeholder:text-text-muted focus-visible:border-border-strong disabled:cursor-not-allowed"
          style={busy ? { opacity: 0.6, cursor: "not-allowed" } : undefined}
        />

        {/* Send is replaced in the same slot by Cancel while busy — no layout shift. */}
        {busy ? (
          <button
            type="button"
            onClick={onCancel}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-md border border-danger px-4 py-2 font-mono-body text-small font-semibold text-danger transition-colors duration-fast ease-standard hover:bg-danger hover:text-accent-on"
          >
            Cancel
          </button>
        ) : (
          <button
            type="button"
            disabled={!canSend}
            onClick={onSend}
            className="flex min-h-11 min-w-11 items-center justify-center rounded-md bg-accent px-4 py-2 font-mono-body text-small font-semibold text-accent-on transition-colors duration-fast ease-standard hover:bg-accent-hover active:bg-accent-active disabled:cursor-not-allowed disabled:bg-transparent disabled:text-text-disabled disabled:border disabled:border-border"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
