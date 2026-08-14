"use client";

import { StatusDot } from "./StatusDot";
import type { SessionStatus } from "./types";

export interface TopBarProps {
  sessionStatus: SessionStatus;
  /**
   * Not in M1_CHAT_SPEC.md §7's literal prop list (only `sessionStatus` is
   * named there), but the same section requires "a minimal sign-out
   * affordance (icon button)" — an inert button would not satisfy that, so
   * this is added as the obvious click handler a real sign-out needs.
   */
  onSignOut: () => void;
}

/**
 * 56px, `bg-surface`, bottom border. No nav in M1 — this is chrome, kept
 * out of the reusable chat components per `DASHBOARD_DIRECTION.md` §2, so
 * only `TopBar` (and `ChatShell`) assume "full viewport, no chrome".
 */
export function TopBar({ sessionStatus, onSignOut }: TopBarProps) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-border bg-surface px-4 sm:px-8">
      <span className="font-display text-h2 uppercase tracking-h2 text-text-secondary">
        <span className="sm:hidden">S</span>
        <span className="hidden sm:inline">S.U.N.I.L</span>
      </span>

      <div className="flex items-center gap-4">
        <StatusDot state={sessionStatus === "active" ? "online" : "offline"} label="Session" />
        <button
          type="button"
          onClick={onSignOut}
          aria-label="Sign out"
          className="flex min-h-11 min-w-11 items-center justify-center rounded-md text-text-secondary transition-colors duration-fast ease-standard hover:text-text-primary"
        >
          <span aria-hidden="true">⎋</span>
        </button>
      </div>
    </header>
  );
}
