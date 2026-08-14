"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ChatShell,
  Composer,
  MessageList,
  TopBar,
  type ActiveTurn,
  type ChatMessage,
} from "@/components/chat";
import { getSession, logout } from "@/lib/api";
import { FALLBACK_KNOWN_PROJECTS, formatTimestamp, suggestionsFor } from "@/lib/copy";
import { useTurn } from "@/lib/useTurn";

/**
 * The M1 chat screen (`M1_CHAT_SPEC.md` §1.1) — single conversation per
 * session, auto-created on first message (FR-022). `page.tsx` wires the
 * presentational T15 components to the real API via `useTurn`; it holds no
 * design decisions of its own beyond that plumbing.
 */
export default function ChatPage() {
  const router = useRouter();
  const [sessionChecked, setSessionChecked] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [composerValue, setComposerValue] = useState("");
  const [expandedTraceIds, setExpandedTraceIds] = useState<ReadonlySet<string>>(new Set());
  const [focusToken, setFocusToken] = useState(0);

  useEffect(() => {
    let cancelled = false;
    getSession()
      .then((session) => {
        if (cancelled) return;
        if (!session.authenticated) {
          router.replace("/login");
        } else {
          setSessionChecked(true);
        }
      })
      .catch(() => {
        if (!cancelled) router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  const toggleTrace = useCallback((id: string) => {
    setExpandedTraceIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }, []);

  const turn = useTurn({ conversationId, onConversationId: setConversationId });

  async function handleSend() {
    const text = composerValue.trim();
    if (!text) return;

    setMessages((prev) => [
      ...prev,
      {
        id: crypto.randomUUID(),
        role: "user",
        content: text,
        timestamp: formatTimestamp(new Date()),
      },
    ]);

    const result = await turn.sendTurn(text);

    if (result.outcome === "ok") {
      const { message, trace } = result;
      setMessages((prev) => [
        ...prev,
        {
          id: message.id,
          role: "assistant",
          content: message.content,
          timestamp: formatTimestamp(message.createdAt),
          trace,
          expanded: false,
          onToggleTrace: () => toggleTrace(message.id),
        },
      ]);
      setComposerValue("");
    }
    // On failure/cancel: the composer's `value` is left exactly as the user
    // typed it — Recovery state (§4) — so a retry/edit needs no re-typing.
  }

  async function handleSignOut() {
    await logout();
    router.replace("/login");
  }

  function handlePickSuggestion(text: string) {
    setComposerValue(text);
    setFocusToken((token) => token + 1);
  }

  // `onEdit` (plan_rejected/unknown_project) only needs to move focus back
  // to the composer — the hook already leaves the original text in place.
  // That's page-level UI, not the hook's concern (see useTurn.ts).
  const displayTurn: ActiveTurn =
    turn.activeTurn?.kind === "error" &&
    (turn.activeTurn.variant === "plan_rejected" || turn.activeTurn.variant === "unknown_project")
      ? { ...turn.activeTurn, onEdit: () => setFocusToken((token) => token + 1) }
      : turn.activeTurn;

  // `messages` is append-only; a toggled trace is derived here from
  // `expandedTraceIds` each render rather than written back into the
  // stored message, so there is exactly one place trace-expansion state
  // lives.
  const renderedMessages: ChatMessage[] = messages.map((message) =>
    message.role === "assistant"
      ? {
          ...message,
          expanded: expandedTraceIds.has(message.id),
          onToggleTrace: () => toggleTrace(message.id),
        }
      : message,
  );

  if (!sessionChecked) return null;

  return (
    <ChatShell
      topBar={<TopBar sessionStatus="active" onSignOut={handleSignOut} />}
      composer={
        <Composer
          value={composerValue}
          onChange={setComposerValue}
          onSend={handleSend}
          onCancel={turn.cancelTurn}
          busy={turn.activeTurn?.kind === "working"}
          focusToken={focusToken}
        />
      }
    >
      <MessageList
        messages={renderedMessages}
        activeTurn={displayTurn}
        onJumpToBottom={() => {}}
        suggestions={suggestionsFor(FALLBACK_KNOWN_PROJECTS)}
        onPickSuggestion={handlePickSuggestion}
      />
    </ChatShell>
  );
}
