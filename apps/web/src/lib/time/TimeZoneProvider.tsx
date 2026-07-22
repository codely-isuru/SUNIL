"use client";

/**
 * `<TimeZoneProvider>` — PORTAL_SHELL_SPEC.md §6.7.
 *
 * "A single `<TimeZoneProvider>` at the shell root supplies the resolved zone. No page reads
 * the setting directly; changing it in Settings re-renders every timestamp in the app without
 * a reload."
 *
 * The value is the RESOLVED IANA name, already through the §6.2 order
 * (user → system → environment → `Australia/Hobart`). Nothing downstream re-resolves, and
 * nothing downstream may fall back to the browser's zone: §6.3 says the device zone is never
 * used silently, only as an explicit choice made in Settings.
 */
import { createContext, createElement, useContext, useMemo, useState } from "react";
import type { JSX, ReactNode } from "react";
import { DEFAULT_TIMEZONE } from "@sunil/ui";

export interface TimeZoneValue {
  readonly timeZone: string;
  /** 24-hour is the Phase 1 default — the prototype's `hour12:false`. */
  readonly hour12: boolean;
  setTimeZone(zone: string): void;
  setHour12(value: boolean): void;
}

const TimeZoneContext = createContext<TimeZoneValue>({
  timeZone: DEFAULT_TIMEZONE,
  hour12: false,
  setTimeZone: () => undefined,
  setHour12: () => undefined,
});

export function TimeZoneProvider({
  initialTimeZone,
  initialHour12 = false,
  children,
}: {
  initialTimeZone: string;
  initialHour12?: boolean;
  children: ReactNode;
}): JSX.Element {
  const [timeZone, setTimeZone] = useState(initialTimeZone);
  const [hour12, setHour12] = useState(initialHour12);
  const value = useMemo<TimeZoneValue>(
    () => ({ timeZone, hour12, setTimeZone, setHour12 }),
    [timeZone, hour12],
  );
  return createElement(TimeZoneContext.Provider, { value }, children);
}

export function useTimeZone(): TimeZoneValue {
  return useContext(TimeZoneContext);
}
