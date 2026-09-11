"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Icon } from "@/components/ui/Icon";
import { StateConflictError } from "@/lib/api";
import {
  decisionReducer,
  initialDecisionState,
  type DecisionKind,
} from "@/lib/decision";
import type { Approval } from "@/lib/types";

/**
 * The decision bar (§6.6–6.7) — the one control surface that moves money.
 *
 * Behaviour that is an acceptance criterion, not a preference:
 *
 * - **Arm then commit.** The first press arms; only the confirm press sends.
 *   `A`/`R` *arm* approve/refuse — a single unguarded keystroke must never
 *   move money — `Enter`/`Space` commits the armed button (native, it has
 *   focus), `Escape` disarms. Shortcuts are ignored while focus is in a text
 *   field, so typing a refusal reason cannot arm anything.
 * - **The glow is a state.** The armed confirm button is the only element on
 *   the page carrying `shadow-glow-armed` + the shimmer sweep (§A.4); the
 *   sweep is removed under `prefers-reduced-motion` by the global kill-switch
 *   and the glow border still carries the state.
 * - **Never optimistic.** While submitting, the label is `Approving…` and both
 *   controls are disabled; the status is NOT changed. The parent re-renders
 *   the card from the server's returned row via `onResolved`.
 * - **409 is rendered verbatim.** The banner states the server's
 *   `current_status` and that nothing was applied (C4 §5). The expiry race has
 *   its own copy because the consequence differs (the task has been failed).
 * - **A lost response is safe.** A network failure says nothing changed and
 *   offers a retry that re-sends the same decision; a 409 on that retry is
 *   handled by the path above, so a double-submit cannot double-refund.
 */

const BTN =
  "inline-flex min-h-[44px] min-w-[124px] items-center justify-center gap-2 rounded-md border px-4 py-2.5 font-body text-body font-semibold disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none";
const PRIMARY = "border-accent bg-accent bg-sheen-metal text-accent-on hover:bg-accent-hover active:bg-accent-active";
const DANGER = "border-danger bg-transparent text-danger hover:bg-danger/10";
const GHOST = "border-border-strong bg-transparent text-accent hover:border-accent hover:bg-surface-high";
const ARMED = "shimmer-sweep relative overflow-hidden shadow-glow-armed";
const ARMED_DANGER = "shimmer-sweep relative overflow-hidden shadow-glow-armed-danger";

export interface DecisionBarProps {
  /** False while the poll is stale (§1.5) — decisions are blocked, not risked. */
  canDecide: boolean;
  blockedReason?: string;
  onSubmit: (kind: DecisionKind, reason?: string) => Promise<Approval>;
  onResolved: (approval: Approval) => void;
}

export function DecisionBar({ canDecide, blockedReason, onSubmit, onResolved }: DecisionBarProps) {
  const [state, dispatch] = useReducer(decisionReducer, initialDecisionState);
  const [reason, setReason] = useState("");
  const confirmRef = useRef<HTMLButtonElement>(null);
  // The callbacks are inline closures at the call site; they are read at
  // request time from refs refreshed after render (never during it), so the
  // commit effect below does not re-fire when the parent re-renders.
  const submitRef = useRef(onSubmit);
  const resolvedRef = useRef(onResolved);
  useEffect(() => {
    submitRef.current = onSubmit;
    resolvedRef.current = onResolved;
  }, [onSubmit, onResolved]);

  const send = useCallback(
    async (kind: DecisionKind, note: string) => {
      const trimmed = note.trim();
      try {
        const row = await submitRef.current(kind, trimmed.length > 0 ? trimmed : undefined);
        dispatch({ type: "resolved", approval: row });
        resolvedRef.current(row);
      } catch (err) {
        if (err instanceof StateConflictError) {
          dispatch({ type: "conflict", currentStatus: err.currentStatus, message: err.message });
          return;
        }
        dispatch({ type: "network_error" });
      }
    },
    [],
  );

  // The commit is driven by the machine entering `submitting`, so the request
  // is issued in exactly one place no matter which control (or key) armed it.
  const submittingKind = state.phase === "submitting" ? state.kind : null;
  const reasonRef = useRef(reason);
  useEffect(() => {
    reasonRef.current = reason;
  }, [reason]);
  useEffect(() => {
    if (submittingKind) void send(submittingKind, reasonRef.current);
  }, [submittingKind, send]);

  // Focus follows the arming, so Enter/Space commits with no extra handler.
  const armedPhaseKind = state.phase === "armed" ? state.kind : null;
  useEffect(() => {
    if (armedPhaseKind) confirmRef.current?.focus();
  }, [armedPhaseKind]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      const target = event.target as HTMLElement | null;
      const typing =
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);
      if (typing || event.metaKey || event.ctrlKey || event.altKey) return;

      if (event.key === "Escape") {
        dispatch({ type: "disarm" });
        return;
      }
      if (!canDecide) return;
      if (event.key === "a" || event.key === "A") dispatch({ type: "arm", kind: "approve" });
      if (event.key === "r" || event.key === "R") dispatch({ type: "arm", kind: "refuse" });
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [canDecide]);

  if (state.phase === "conflict") {
    const expired = state.currentStatus === "expired";
    return (
      <div className="bg-surface-raised px-5 py-4">
        <div
          role="alert"
          className="flex items-start gap-2.5 rounded-md border border-danger bg-surface-raised px-3.5 py-3 text-cell text-danger"
        >
          <Icon name={expired ? "ban" : "alert-triangle"} />
          <div>
            {expired ? (
              <>
                <b>This approval expired before your decision landed.</b>
                <br />
                <span className="text-small">
                  {"The task has been failed as "}
                  <span className="font-mono text-[0.6875rem]">approval_expired</span>
                  {" and nothing ran. Ask SUNIL again if you still want it. Your decision was not applied."}
                </span>
              </>
            ) : (
              <>
                <b>{`This was already ${state.currentStatus} — your decision was not applied.`}</b>
                <br />
                <span className="text-small">
                  {"The server reports "}
                  <span className="font-mono text-[0.6875rem]">{`current_status = ${state.currentStatus}`}</span>
                  {". Nothing you just pressed changed anything."}
                </span>
              </>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (state.phase === "decided") {
    // The parent re-renders the whole card from the server row; the bar is
    // replaced by the decision receipt (§6.7 Success).
    return null;
  }

  const armedKind = state.phase === "armed" ? state.kind : null;
  const busyKind = state.phase === "submitting" ? state.kind : null;
  const failedKind = state.phase === "network_error" ? state.kind : null;

  return (
    <div className="bg-surface-raised px-5 py-4">
      {failedKind ? (
        <div
          role="alert"
          className="mb-3.5 flex items-start gap-2.5 rounded-md border border-danger bg-surface-raised px-3.5 py-3 text-cell text-danger"
        >
          <Icon name="alert-triangle" />
          <div>
            <b>Your decision didn&apos;t reach SUNIL — nothing has changed.</b>
            <br />
            <span className="text-small">
              Try again. If it had in fact landed, the retry is answered with a conflict and you
              will see the real status — nothing is applied twice.
            </span>
          </div>
        </div>
      ) : null}

      {armedKind === "refuse" || (failedKind === "refuse" && reason) ? (
        <div className="mb-3.5">
          <label
            htmlFor="decision-reason"
            className="text-micro font-semibold uppercase tracking-micro text-text-muted"
          >
            Reason (optional, max 1000)
          </label>
          <textarea
            id="decision-reason"
            rows={2}
            maxLength={1000}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="mt-1.5 w-full rounded-md border border-border bg-surface-high px-2.5 py-2.5 font-body text-cell text-text-primary"
          />
        </div>
      ) : null}

      {armedKind ? (
        <div className="flex flex-wrap items-center gap-3.5">
          <span className="flex-1 text-small text-text-muted">
            {armedKind === "approve"
              ? "This runs the action once, now. There is no undo."
              : "This refuses the action for good. There is no undo — you can always ask SUNIL again from chat."}
          </span>
          <button type="button" className={`${BTN} ${GHOST}`} onClick={() => dispatch({ type: "disarm" })}>
            Cancel
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={`${BTN} ${armedKind === "approve" ? `${PRIMARY} ${ARMED}` : `${DANGER} ${ARMED_DANGER}`}`}
            onClick={() => dispatch({ type: "commit" })}
          >
            <Icon name={armedKind === "approve" ? "check" : "x"} />
            {armedKind === "approve" ? "Confirm approve" : "Confirm refuse"}
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-3.5">
          <span className="flex-1 text-small text-text-muted">
            {canDecide ? (
              <>
                Keyboard: <Kbd>R</Kbd> arms refuse · <Kbd>A</Kbd> arms approve · <Kbd>Enter</Kbd>{" "}
                commits · <Kbd>Esc</Kbd> cancels
              </>
            ) : (
              <span className="text-warning">{blockedReason}</span>
            )}
          </span>
          <button
            type="button"
            disabled={!canDecide || busyKind !== null}
            aria-describedby="decision-consequence"
            className={`${BTN} ${DANGER}`}
            onClick={() =>
              failedKind === "refuse"
                ? dispatch({ type: "commit" })
                : dispatch({ type: "arm", kind: "refuse" })
            }
          >
            {busyKind === "refuse" ? (
              <>
                <Spinner />
                Refusing…
              </>
            ) : failedKind === "refuse" ? (
              "Try again"
            ) : (
              <>
                <Icon name="x" />
                Refuse
              </>
            )}
          </button>
          <button
            type="button"
            disabled={!canDecide || busyKind !== null}
            aria-describedby="decision-consequence"
            className={`${BTN} ${PRIMARY}`}
            onClick={() =>
              failedKind === "approve"
                ? dispatch({ type: "commit" })
                : dispatch({ type: "arm", kind: "approve" })
            }
          >
            {busyKind === "approve" ? (
              <>
                <Spinner />
                Approving…
              </>
            ) : failedKind === "approve" ? (
              "Try again"
            ) : (
              <>
                <Icon name="check" />
                Approve this action
              </>
            )}
          </button>
          <span id="decision-consequence" className="sr-only">
            Decisions are final and cannot be undone. Approving executes this action once, within
            one hour.
          </span>
        </div>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <span
      aria-hidden="true"
      className="inline-block h-3.5 w-3.5 animate-spin-sm rounded-full border-2 border-current border-r-transparent"
    />
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded-sm border border-b-2 border-border bg-surface-high px-1.5 py-px font-mono text-[0.6875rem] text-text-secondary">
      {children}
    </kbd>
  );
}
