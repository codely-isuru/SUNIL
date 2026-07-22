"use client";

/**
 * The header clock — PORTAL_SHELL_SPEC.md §4.2 and §6.
 *
 * Three things here are not decoration:
 *   - the zone comes from the resolved SETTING via `<TimeZoneProvider>`, never from the host,
 *     and the abbreviation is DERIVED per instant, so Hobart reads AEDT in summer and AEST in
 *     winter (the prototype printed `MELBOURNE · AEST` all year, for the wrong city);
 *   - the ticking element is `aria-hidden`, and a sibling `.sr-only` node carries the time at
 *     MINUTE granularity with no live region. A per-second live region is unusable;
 *   - the interval is cleared on unmount and paused while `document.hidden`.
 *
 * The first render is `--:--:--`, matching the prototype's initial markup and keeping the
 * server and client output identical so hydration cannot mismatch on a moving value.
 *
 * The formatting itself lives in `clockView`, which is pure and directly asserted by
 * `src/__tests__/clock.test.ts`.
 */
import { useEffect, useState } from "react";
import type { JSX } from "react";
import { zoneCity } from "@sunil/ui";
import { CLOCK_PLACEHOLDER, clockView } from "../lib/time/clockView";
import { useTimeZone } from "../lib/time/TimeZoneProvider";

export function HeaderClock(): JSX.Element {
  const { timeZone, hour12 } = useTimeZone();
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    const tick = (): void => {
      if (document.hidden) return;
      setNow(new Date());
    };
    tick();
    const interval = setInterval(tick, 1000);
    document.addEventListener("visibilitychange", tick);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", tick);
    };
  }, []);

  const view = now === null ? null : clockView(now, timeZone, hour12);

  return (
    <div className="sunil-clock">
      <span
        className="sunil-clock__time sunil-type-display-sm"
        aria-hidden="true"
        title={view?.isoTitle}
      >
        {view === null ? CLOCK_PLACEHOLDER : view.time}
      </span>
      <span className="sunil-clock__zone sunil-type-micro" aria-hidden="true">
        {view === null ? zoneCity(timeZone) : view.zoneLabel}
      </span>
      {/* Read on demand, not announced: minute granularity, no aria-live. */}
      <span className="sunil-sr-only">
        {view === null ? `Time unavailable. ${zoneCity(timeZone)}.` : view.screenReaderText}
      </span>
    </div>
  );
}
