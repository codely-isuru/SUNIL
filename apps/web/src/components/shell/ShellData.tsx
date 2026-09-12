"use client";

import { createContext, useContext, type ReactNode } from "react";
import { listApprovals } from "@/lib/api";
import { usePoll } from "@/lib/usePoll";
import type { Approval } from "@/lib/types";

/**
 * One poll for the chrome (§1.5): the rail badge and the topbar's pending chip
 * and freshness indicator all read the **same** `?status=pending` request, so
 * they can never disagree with each other. The badge clears only because the
 * server says so — nothing here decrements it locally.
 */

export interface ShellDataValue {
  pending: Approval[];
  pendingCount: number;
  ageMs: number | null;
  lastSuccessAt: number | null;
  stale: boolean;
  loading: boolean;
  error: unknown;
  refresh: () => void;
}

const ShellDataContext = createContext<ShellDataValue | null>(null);

export function ShellDataProvider({ children }: { children: ReactNode }) {
  const poll = usePoll(() => listApprovals({ status: "pending", limit: 200 }));
  const pending = poll.data?.approvals ?? [];

  const value: ShellDataValue = {
    pending,
    pendingCount: pending.length,
    ageMs: poll.ageMs,
    lastSuccessAt: poll.lastSuccessAt,
    stale: poll.stale,
    loading: poll.loading,
    error: poll.error,
    refresh: poll.refresh,
  };

  return <ShellDataContext.Provider value={value}>{children}</ShellDataContext.Provider>;
}

export function useShellData(): ShellDataValue {
  const value = useContext(ShellDataContext);
  if (!value) {
    throw new Error("useShellData must be used inside <ShellDataProvider>");
  }
  return value;
}
