"use client";

import { useEffect, useRef, useState } from "react";
import { AssistantMessage } from "./AssistantMessage";
import { ErrorCard } from "./ErrorCard";
import { JumpToBottomPill } from "./JumpToBottomPill";
import { MessageBubble } from "./MessageBubble";
import { SuggestionChips } from "./SuggestionChips";
import type { ActiveTurn, ChatMessage } from "./types";
import { WorkIndicator } from "./WorkIndicator";

export interface MessageListProps {
  messages: ChatMessage[];
  activeTurn: ActiveTurn;
  onJumpToBottom: () => void;
  /**
   * FR-107 configured project names for the empty-state chips (§3). Share
   * this source with the `unknown_project` ErrorCard's project list so the
   * two never drift out of sync (§5.9).
   */
  suggestions: string[];
  onPickSuggestion: (text: string) => void;
}

const SCROLL_UP_THRESHOLD_PX = 100;

function EmptyState({
  suggestions,
  onPick,
}: {
  suggestions: string[];
  onPick: (text: string) => void;
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 py-16 text-center">
      <span
        aria-hidden="true"
        className="inline-block h-10 w-10 rounded-full border-2 border-accent shadow-glow-hover"
      />
      <h1 className="font-display text-h1 uppercase tracking-h1 text-text-primary">
        Ask me to check on something.
      </h1>
      <SuggestionChips suggestions={suggestions} onPick={onPick} />
    </div>
  );
}

/**
 * `EmptyState` is not its own file in `docs/design/M1_CHAT_SPEC.md` §7's
 * component table — that table lists twelve components and this is not one
 * of them, but §2's composition tree and §3's full spec both require it as
 * a child MessageList renders when `messages.length === 0`. Kept private to
 * this file rather than invented as a thirteenth top-level component.
 */
export function MessageList({
  messages,
  activeTurn,
  onJumpToBottom,
  suggestions,
  onPickSuggestion,
}: MessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [isScrolledUp, setIsScrolledUp] = useState(false);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || isScrolledUp) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, activeTurn, isScrolledUp]);

  function handleScroll() {
    const el = scrollRef.current;
    if (!el) return;
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setIsScrolledUp(distanceFromBottom > SCROLL_UP_THRESHOLD_PX);
  }

  function scrollToBottom() {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    setIsScrolledUp(false);
    onJumpToBottom();
  }

  if (messages.length === 0) {
    return (
      <div className="flex flex-1 flex-col overflow-y-auto px-4 py-6 sm:px-8">
        <EmptyState suggestions={suggestions} onPick={onPickSuggestion} />
      </div>
    );
  }

  // Announce only the latest *assistant* content (§8) — the user's own sent
  // messages don't need re-announcing, they typed them.
  const latestAssistant = [...messages].reverse().find((message) => message.role === "assistant");

  return (
    <div className="relative flex flex-1 flex-col overflow-hidden">
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto px-4 py-6 sm:px-8"
      >
        <div className="mx-auto flex max-w-3xl flex-col gap-4">
          {messages.map((message) =>
            message.role === "user" ? (
              <MessageBubble key={message.id} content={message.content} timestamp={message.timestamp} />
            ) : (
              <AssistantMessage
                key={message.id}
                content={message.content}
                timestamp={message.timestamp}
                trace={message.trace}
                expanded={message.expanded}
                onToggleTrace={message.onToggleTrace}
              />
            ),
          )}

          {activeTurn?.kind === "working" && (
            <WorkIndicator
              phase={activeTurn.phase}
              dynamicLabel={activeTurn.dynamicLabel}
              elapsedSeconds={activeTurn.elapsedSeconds}
              showReassurance={activeTurn.showReassurance}
              onCancel={activeTurn.onCancel}
            />
          )}
          {activeTurn?.kind === "error" && (
            <ErrorCard
              variant={activeTurn.variant}
              message={activeTurn.message}
              onRetry={activeTurn.onRetry}
              onEdit={activeTurn.onEdit}
            />
          )}
          {activeTurn?.kind === "cancelled" && (
            <p
              role="status"
              aria-live="polite"
              className="px-4 text-center font-mono-body text-small text-text-muted"
            >
              You cancelled this. I&rsquo;ll stop showing progress for it — it won&rsquo;t appear
              as a reply, even if I finish it in the background.
            </p>
          )}
        </div>
      </div>

      <div aria-live="polite" className="sr-only">
        {latestAssistant?.content}
      </div>

      <JumpToBottomPill visible={isScrolledUp} onClick={scrollToBottom} />
    </div>
  );
}
