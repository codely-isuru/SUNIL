"use client";

/**
 * Polling for `GET /api/system-health` — the only live data source in Phase 1.
 *
 * Shared by the header status pill (30s, §4.1) and the System Health page (15s, §10.2) so the
 * pause and back-off rules exist once:
 *   - polling is PAUSED while `document.hidden`. A background tab hammering a health endpoint
 *     every 15 seconds is a self-inflicted denial of service;
 *   - on failure the interval backs off 15s → 30s → 60s and caps there (§10.3);
 *   - a state CHANGE is announced; an unchanged poll announces nothing. A live region that
 *     speaks every 15 seconds is a screen-reader denial of service (§4.1);
 *   - the request is never fired from a server render, so `next build` never depends on the
 *     API being up.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchSystemHealth } from "./client";
import type { ApiFailureKind, SystemHealthResponse } from "./types";

export type HealthPhase = "loading" | "success" | "error";

export interface HealthState {
  readonly phase: HealthPhase;
  readonly data: SystemHealthResponse | null;
  readonly failure: ApiFailureKind | null;
  readonly httpStatus: number | null;
  readonly lastCheckedAt: Date | null;
  /** True for the very first load only: subsequent refreshes never re-skeleton (§10.3). */
  readonly firstLoad: boolean;
}

const BACKOFF_MS = [15_000, 30_000, 60_000];

export function useSystemHealth(intervalMs: number, enabled = true): HealthState & {
  refresh: () => void;
} {
  const [state, setState] = useState<HealthState>({
    phase: "loading",
    data: null,
    failure: null,
    httpStatus: null,
    lastCheckedAt: null,
    firstLoad: true,
  });
  const failuresRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async () => {
    const result = await fetchSystemHealth();
    if (result.ok) {
      failuresRef.current = 0;
      setState({
        phase: "success",
        data: result.data,
        failure: null,
        httpStatus: null,
        lastCheckedAt: new Date(),
        firstLoad: false,
      });
      return;
    }
    failuresRef.current += 1;
    setState((previous) => ({
      phase: "error",
      // Keep the last known payload so the page can keep its shape; the caller decides
      // whether to show it. A vanished card reads as "fine", which is the opposite of true.
      data: previous.data,
      failure: result.kind,
      httpStatus: result.status ?? null,
      lastCheckedAt: new Date(),
      firstLoad: false,
    }));
  }, []);

  const refresh = useCallback(() => {
    void poll();
  }, [poll]);

  useEffect(() => {
    if (!enabled) return undefined;
    let cancelled = false;

    const schedule = (): void => {
      if (cancelled) return;
      const failures = failuresRef.current;
      const delay =
        failures === 0
          ? intervalMs
          : (BACKOFF_MS[Math.min(failures - 1, BACKOFF_MS.length - 1)] ?? intervalMs);
      timerRef.current = setTimeout(run, delay);
    };

    const run = async (): Promise<void> => {
      if (cancelled) return;
      if (!document.hidden) await poll();
      schedule();
    };

    void run();

    const onVisibility = (): void => {
      if (!document.hidden) void poll();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      cancelled = true;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [enabled, intervalMs, poll]);

  return { ...state, refresh };
}

/** The lamp/label pair for a health phase — §4.1's table, in one place. */
export function statusPresentation(state: HealthState): {
  lamp: "on" | "warn" | "error" | "off" | "unknown";
  label: string;
} {
  if (state.phase === "loading") return { lamp: "unknown", label: "CHECKING" };
  if (state.phase === "error") return { lamp: "off", label: "NO SIGNAL" };
  const status = state.data?.status;
  // As-built, the API returns the literal `"ok"`; §13 words the same field `healthy`.
  // Anything else is UNKNOWN — an unrecognised status is never rendered as good.
  if (status === "ok" || status === "healthy") return { lamp: "on", label: "NOMINAL" };
  if (status === "degraded") return { lamp: "warn", label: "DEGRADED" };
  if (status === "unhealthy") return { lamp: "error", label: "FAULT" };
  return { lamp: "unknown", label: "UNKNOWN" };
}
