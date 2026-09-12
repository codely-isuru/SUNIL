"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The §1.5 poll, once, for every view.
 *
 * C4 §2 fixes the mechanism: `GET …?status=pending` every 10 s, no push
 * channel in Phase 0/1. This hook is where the spec's honesty rules live:
 *
 * - the last **successful** poll is timestamped, and `secondsSinceSuccess`
 *   drives the freshness chip;
 * - **stale** is >30 s since a success (i.e. a poll has failed). Stale keeps
 *   the last good data on screen and blocks decisions — it never blanks the
 *   list and never clears a badge locally;
 * - a refresh with data on screen does **not** re-enter the loading state
 *   (§2.1 "Loading (refresh)"), so no skeleton flashes over live rows;
 * - polling pauses while the document is hidden and polls immediately on
 *   `visibilitychange`.
 */

export const POLL_INTERVAL_MS = 10_000;
export const STALE_AFTER_MS = 30_000;

export interface PollState<T> {
  data: T | null;
  /** First paint only — true while there is nothing to show yet. */
  loading: boolean;
  error: unknown;
  /** ms since the last successful poll, or null before the first success. */
  ageMs: number | null;
  /** Epoch ms of the last successful poll — the "showing data from" stamp. */
  lastSuccessAt: number | null;
  stale: boolean;
  refresh: () => void;
}

export function usePoll<T>(
  fetcher: () => Promise<T>,
  options: { intervalMs?: number; enabled?: boolean } = {},
): PollState<T> {
  const { intervalMs = POLL_INTERVAL_MS, enabled = true } = options;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [lastSuccessAt, setLastSuccessAt] = useState<number | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());

  const fetcherRef = useRef(fetcher);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  // The fetcher is an inline closure at every call site, so it is kept in a
  // ref and refreshed after render (never during it) — the poll interval must
  // not be torn down and rebuilt ten times a second because of it.
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  const run = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const next = await fetcherRef.current();
      if (!mounted.current) return;
      setData(next);
      setError(null);
      setLastSuccessAt(Date.now());
    } catch (err) {
      if (!mounted.current) return;
      // Deliberately keep `data` — the last good snapshot stays on screen
      // behind the stale banner (§1.5).
      setError(err);
    } finally {
      inFlight.current = false;
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void run();
    const id = window.setInterval(() => {
      if (typeof document !== "undefined" && document.hidden) return;
      void run();
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [enabled, intervalMs, run]);

  // Immediate poll when the tab comes back — a 4-minute-old queue behind a
  // freshly focused window is exactly how an owner decides something twice.
  useEffect(() => {
    if (!enabled) return;
    const onVisible = () => {
      if (!document.hidden) void run();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [enabled, run]);

  // The freshness chip ticks once a second; nothing else re-renders on it.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(id);
  }, []);

  const ageMs = lastSuccessAt === null ? null : Math.max(0, now - lastSuccessAt);

  return {
    data,
    loading: data === null && error === null,
    error,
    ageMs,
    lastSuccessAt,
    stale: ageMs !== null && ageMs > STALE_AFTER_MS,
    refresh: () => void run(),
  };
}

/**
 * The countdown clock (§6.5): every visible countdown re-renders on **one**
 * shared 30s tick, not a per-second timer. A per-second repaint on a 72-hour
 * window is noise, and the live region is announced at threshold crossings
 * only — never on a tick.
 */
export function useTick(intervalMs = 30_000): number {
  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** One-shot load for a detail route (no poll needed until a decision lands). */
export function useAsync<T>(fetcher: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  const reload = useCallback(() => {
    let cancelled = false;
    setLoading(true);
    fetcherRef
      .current()
      .then((next) => {
        if (!cancelled) {
          setData(next);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Fetching on mount IS an external-system sync, and `loading` has to flip
  // when the request starts — the cascading-render warning does not apply.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(reload, [reload, ...deps]);

  return { data, error, loading, setData, reload };
}
