"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ActiveTurn, ErrorVariant, TraceStep, WorkPhase } from "@/components/chat";
import { openProgressEvents, sendChatTurn } from "./api";
import { formatKnownProjectList, formatTraceStep } from "./copy";
import { dynamicLabelFromDetail, phaseForStage, type StageName } from "./phases";

const MIN_PHASE_DISPLAY_MS = 400;
const REASSURANCE_AT_S = 20;
const CLIENT_TIMEOUT_S = 45;
const FINISHING_HOLD_MS = 1000;

export interface TurnMessage {
  id: string;
  content: string;
  createdAt: string;
}

export type TurnResult =
  | { outcome: "ok"; message: TurnMessage; trace: TraceStep[] }
  | { outcome: "failed" };

interface UseTurnArgs {
  /** Read via a ref internally — always the latest value, no stale closures across an in-flight turn. */
  conversationId: string | null;
  onConversationId: (conversationId: string) => void;
}

/**
 * The one hook that owns a turn (`ARCHITECTURE_V1.md` §12): mints the
 * `request_id`, opens the optional SSE channel, POSTs with an
 * `AbortController`, maps stage events to one of the four visible phases,
 * enforces the 400ms minimum phase display and the 20s/45s thresholds, and
 * resolves to a message + trace or an `ErrorCard` variant.
 *
 * Progressive enhancement, not a branch: the deterministic fallback
 * schedule (M1_CHAT_SPEC.md §5.3's fallback variant) always starts
 * immediately. If a real `stage` event arrives (T12 built and
 * `SUNIL_PROGRESS_EVENTS=true`), it pre-empts the schedule from that point
 * on; if none ever arrives, the schedule runs to completion untouched.
 * `WorkIndicator` never knows which source is active — exactly the
 * swappable-without-a-redesign property T15 was built to keep.
 */
export function useTurn({ conversationId, onConversationId }: UseTurnArgs) {
  const [activeTurn, setActiveTurn] = useState<ActiveTurn>(null);

  const conversationIdRef = useRef(conversationId);
  useEffect(() => {
    conversationIdRef.current = conversationId;
  }, [conversationId]);

  const abortRef = useRef<AbortController | null>(null);
  const closeEventsRef = useRef<(() => void) | null>(null);
  const fallbackTimersRef = useRef<number[]>([]);
  const elapsedIntervalRef = useRef<number | null>(null);
  const liveRef = useRef(false);
  const lastPhaseChangeAtRef = useRef(0);
  const startedAtRef = useRef(0);

  const clearFallbackTimers = useCallback(() => {
    fallbackTimersRef.current.forEach((id) => window.clearTimeout(id));
    fallbackTimersRef.current = [];
  }, []);

  const clearElapsedInterval = useCallback(() => {
    if (elapsedIntervalRef.current !== null) {
      window.clearInterval(elapsedIntervalRef.current);
      elapsedIntervalRef.current = null;
    }
  }, []);

  const teardown = useCallback(() => {
    closeEventsRef.current?.();
    closeEventsRef.current = null;
    clearFallbackTimers();
    clearElapsedInterval();
  }, [clearFallbackTimers, clearElapsedInterval]);

  // One aria-live-friendly phase change at a time: never set a new phase
  // sooner than 400ms after the last one (§5.3 — "prevents flicker on fast
  // tool calls"), whichever source (live or fallback) is producing it.
  const setPhase = useCallback((phase: WorkPhase, dynamicLabel?: string) => {
    const now = Date.now();
    const remaining = Math.max(0, MIN_PHASE_DISPLAY_MS - (now - lastPhaseChangeAtRef.current));
    const apply = () => {
      lastPhaseChangeAtRef.current = Date.now();
      setActiveTurn((prev) => (prev && prev.kind === "working" ? { ...prev, phase, dynamicLabel } : prev));
    };
    if (remaining === 0) {
      apply();
    } else {
      window.setTimeout(apply, remaining);
    }
  }, []);

  const cancelTurn = useCallback(() => {
    abortRef.current?.abort();
    teardown();
    setActiveTurn({ kind: "cancelled" });
  }, [teardown]);

  // `sendTurn`'s own `onRetry` closures need to call `sendTurn` again
  // ("re-submits the exact same original user message", §5.6/§5.7). A
  // `useCallback` cannot reference its own binding inside its initializer
  // (the current `eslint-config-next`/React Compiler lint flags that as
  // "accessed before declared", since the compiler can't reason about a
  // memoized function calling itself through its own not-yet-assigned
  // variable). Indirecting through a ref — written in an effect, not
  // during render — breaks that cycle.
  const sendTurnRef = useRef<((message: string) => Promise<TurnResult>) | null>(null);

  const sendTurn = useCallback(
    async (message: string): Promise<TurnResult> => {
      // Only one turn in flight at a time in M1 (no concurrent-turn design).
      teardown();
      abortRef.current?.abort();

      const requestId = crypto.randomUUID();
      const controller = new AbortController();
      abortRef.current = controller;
      liveRef.current = false;
      lastPhaseChangeAtRef.current = Date.now();
      startedAtRef.current = Date.now();

      setActiveTurn({
        kind: "working",
        phase: "understanding",
        elapsedSeconds: 0,
        showReassurance: false,
        onCancel: cancelTurn,
      });

      elapsedIntervalRef.current = window.setInterval(() => {
        const elapsed = Math.floor((Date.now() - startedAtRef.current) / 1000);
        setActiveTurn((prev) =>
          prev && prev.kind === "working"
            ? { ...prev, elapsedSeconds: elapsed, showReassurance: elapsed >= REASSURANCE_AT_S }
            : prev,
        );
        if (elapsed >= CLIENT_TIMEOUT_S) {
          controller.abort();
        }
      }, 1000);

      closeEventsRef.current = openProgressEvents(requestId, {
        onStage: ({ stage, detail }) => {
          liveRef.current = true;
          clearFallbackTimers();
          setPhase(phaseForStage(stage as StageName), dynamicLabelFromDetail(detail));
        },
        onError: () => {
          // Identical to `SUNIL_PROGRESS_EVENTS` being off — the fallback
          // schedule already running is the entire recovery (no user-visible
          // error for a purely cosmetic channel, ADR-009).
        },
      });

      // The fallback schedule (§5.3's fallback variant): Understanding
      // 0-3s, Planning 3-5s, Working 5s→response. Each check defers to
      // whichever phase a real event has already produced.
      fallbackTimersRef.current.push(
        window.setTimeout(() => {
          if (!liveRef.current) setPhase("planning");
        }, 3000),
      );
      fallbackTimersRef.current.push(
        window.setTimeout(() => {
          if (!liveRef.current) setPhase("working");
        }, 5000),
      );

      const retry = () => sendTurnRef.current?.(message) ?? Promise.resolve({ outcome: "failed" as const });

      try {
        const response = await sendChatTurn({
          message,
          conversationId: conversationIdRef.current,
          requestId,
          signal: controller.signal,
        });

        teardown();

        if (response.conversation_id) onConversationId(response.conversation_id);

        if (response.outcome === "ok" && response.message) {
          setPhase("finishing");
          await wait(FINISHING_HOLD_MS);
          setActiveTurn(null);
          return {
            outcome: "ok",
            message: {
              id: response.message.id,
              content: response.message.content,
              createdAt: response.message.created_at,
            },
            trace: response.trace.map((entry) =>
              formatTraceStep(entry.stage, entry.offset_ms, entry.detail),
            ),
          };
        }

        const variant = mapFailureKind(response.failure?.kind);
        setActiveTurn({
          kind: "error",
          variant,
          message: response.failure?.known_projects
            ? formatKnownProjectList(response.failure.known_projects)
            : undefined,
          // `onRetry` (generic/tool_failed) re-sends this exact message —
          // a turn concern the hook owns directly. `onEdit` (plan_rejected/
          // unknown_project) only needs to move DOM focus to the composer,
          // which already holds the original text (Recovery state, §4) —
          // that's a page-level UI concern, not the hook's; the page
          // attaches `onEdit` when it renders this turn.
          onRetry: variant === "generic" || variant === "tool_failed" ? retry : undefined,
        });
        return { outcome: "failed" };
      } catch {
        // A thrown `ApiError` (401/403/422/429/500) or an abort both land
        // here — both are transport-level or client-abandoned, not one of
        // the four `failure.kind` values (§11.3), so both surface as the
        // generic card unless a cancel already claimed this activeTurn.
        teardown();

        setActiveTurn((prev) => {
          // `cancelTurn` already set 'cancelled' synchronously before the
          // abort propagated here — a client-initiated cancel is not an
          // error and must not be overwritten by one.
          if (prev?.kind === "cancelled") return prev;
          return { kind: "error", variant: "generic", onRetry: retry };
        });
        return { outcome: "failed" };
      }
    },
    [cancelTurn, clearFallbackTimers, onConversationId, setPhase, teardown],
  );

  useEffect(() => {
    sendTurnRef.current = sendTurn;
  }, [sendTurn]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      teardown();
    };
  }, [teardown]);

  return { activeTurn, sendTurn, cancelTurn };
}

function mapFailureKind(kind?: string): ErrorVariant {
  switch (kind) {
    case "tool_failed":
      return "tool_failed";
    case "plan_rejected":
      return "plan_rejected";
    case "unknown_project":
      return "unknown_project";
    case "provider_error":
    default:
      return "generic";
  }
}

function wait(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}
