/**
 * Shared prop/data types for the M1 chat component tree.
 * Source of truth for shape and behaviour: docs/design/M1_CHAT_SPEC.md §7.
 *
 * These components are presentational only — no data fetching, no
 * `fetch`/`EventSource` calls live here. Wiring them to the real API is
 * T16's job (`lib/api.ts`, `lib/useTurn.ts`).
 */

/** One line of the human-readable trace (§5.5) — already formatted by the caller. */
export interface TraceStep {
  label: string;
  offset: string; // e.g. "+2.1s"
}

export interface UserChatMessage {
  id: string;
  role: "user";
  content: string;
  timestamp: string; // pre-formatted by the caller, e.g. "10:41 am"
}

export interface AssistantChatMessage {
  id: string;
  role: "assistant";
  content: string; // markdown
  timestamp: string;
  trace: TraceStep[];
  expanded: boolean;
  onToggleTrace: () => void;
}

export type ChatMessage = UserChatMessage | AssistantChatMessage;

/** The four visible phases a turn compresses the twelve NFR-020 stages into (§5.3). */
export type WorkPhase = "understanding" | "planning" | "working" | "finishing";

export interface WorkingTurn {
  kind: "working";
  phase: WorkPhase;
  /** Substituted into the "Working" phase label once the plan names a project/tool (§5.3). */
  dynamicLabel?: string;
  elapsedSeconds: number;
  showReassurance: boolean;
  onCancel: () => void;
}

/** `failure.kind` → `ErrorCard` variant mapping is fixed by the frozen contract (§6). */
export type ErrorVariant = "generic" | "tool_failed" | "plan_rejected" | "unknown_project";

export interface ErrorTurn {
  kind: "error";
  variant: ErrorVariant;
  /** Formatted "{Project A}, {Project B}" list — `unknown_project` variant only (§5.9). */
  message?: string;
  onRetry?: () => void;
  onEdit?: () => void;
}

/**
 * Cancel (§6) replaces `WorkIndicator` with "a small, neutral, centred
 * system note (not a bubble, not danger-styled — cancellation is not an
 * error)" — a third visual state `ErrorCard`'s four variants don't cover.
 * Added here while wiring T16's `useTurn`, as a small follow-on refinement
 * to a T15 file discovered by the dependent work, not a rewrite of it.
 */
export interface CancelledTurn {
  kind: "cancelled";
}

export type ActiveTurn = WorkingTurn | ErrorTurn | CancelledTurn | null;

export type SessionStatus = "active";
