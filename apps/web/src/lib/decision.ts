import type { Approval, ApprovalStatus } from "./types";

export type DecisionKind = "approve" | "refuse";

export type DecisionState =
  | { phase: "idle" }
  | { phase: "armed"; kind: DecisionKind }
  | { phase: "submitting"; kind: DecisionKind }
  | { phase: "decided"; approval: Approval }
  | { phase: "conflict"; currentStatus: ApprovalStatus; message: string }
  | { phase: "network_error"; kind: DecisionKind };

export type DecisionEvent =
  | { type: "arm"; kind: DecisionKind }
  | { type: "disarm" }
  | { type: "commit" }
  | { type: "resolved"; approval: Approval }
  | { type: "conflict"; currentStatus: ApprovalStatus; message: string }
  | { type: "network_error" };

export const initialDecisionState: DecisionState = { phase: "idle" };

export function isDecisionBusy(state: DecisionState): boolean {
  return state.phase === "submitting";
}

/**
 * The approval card's decision machine (spec §6.7).
 *
 * Three rules are load-bearing and deliberately encoded here rather than in a
 * component, so they are unit-testable and cannot be "optimised away":
 *
 * 1. **Arm then commit.** A decision is only ever sent from `armed`; a commit
 *    raised in any other non-retry phase is dropped. One unguarded keystroke
 *    or stray click can never move money (§6.6).
 * 2. **Never optimistic.** `submitting` does not change the rendered status.
 *    `decided` carries the server's `Approval` row — the pressed intent is
 *    never used to synthesise a status (C4 §5).
 * 3. **409 is the honest path.** `conflict` carries the server's
 *    `current_status` + message for verbatim rendering; it is terminal, so a
 *    conflicted card cannot be re-armed without a re-fetch.
 */
export function decisionReducer(state: DecisionState, event: DecisionEvent): DecisionState {
  switch (event.type) {
    case "arm":
      // Terminal phases are not re-armable; an in-flight submit is not either.
      if (state.phase === "decided" || state.phase === "conflict") return state;
      if (state.phase === "submitting") return state;
      return { phase: "armed", kind: event.kind };

    case "disarm":
      // An in-flight decision cannot be cancelled — the server may already
      // have applied it. Terminal phases have nothing to disarm.
      if (state.phase === "armed") return { phase: "idle" };
      if (state.phase === "network_error") return { phase: "idle" };
      return state;

    case "commit":
      // The only two phases a request may leave from: a freshly armed control,
      // or a retry after a failed send (safe — a 409 on retry is handled).
      if (state.phase === "armed" || state.phase === "network_error") {
        return { phase: "submitting", kind: state.kind };
      }
      return state;

    case "resolved":
      if (state.phase !== "submitting") return state;
      return { phase: "decided", approval: event.approval };

    case "conflict":
      if (state.phase !== "submitting") return state;
      return {
        phase: "conflict",
        currentStatus: event.currentStatus,
        message: event.message,
      };

    case "network_error":
      if (state.phase !== "submitting") return state;
      return { phase: "network_error", kind: state.kind };

    default:
      return state;
  }
}
