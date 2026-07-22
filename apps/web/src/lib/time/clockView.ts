/**
 * The header clock's presentation, as a pure function.
 *
 * It is pure so the §6.8 assertion can be made directly against what the header renders: with
 * the setting at `Australia/Hobart` and the host clock anywhere at all, the clock shows AEDT
 * and an 11-hour offset on a DST date. A formatter that reads the host zone would pass a test
 * written on an Australian machine and fail in CI; this one cannot, because the zone is an
 * argument and there is no other source of it in the function.
 */
import {
  formatClockTime,
  formatMinuteGranularity,
  isoWithOffset,
  zoneAbbreviation,
  zoneCity,
} from "@sunil/ui";

export interface ClockView {
  /** `HH:MM:SS` in the resolved zone. */
  readonly time: string;
  /** e.g. `Hobart · AEDT` — the abbreviation is derived per instant, never hard-coded. */
  readonly zoneLabel: string;
  /** ISO 8601 with offset, for the `title` attribute (§6.6). */
  readonly isoTitle: string;
  /** Minute granularity for the `.sr-only` sibling; a per-second live region is unusable. */
  readonly screenReaderText: string;
}

export function clockView(now: Date, timeZone: string, hour12 = false): ClockView {
  const label = `${zoneCity(timeZone)} · ${zoneAbbreviation(now, timeZone)}`;
  return {
    time: formatClockTime(now, { timeZone, hour12 }),
    zoneLabel: label,
    isoTitle: isoWithOffset(now, timeZone),
    screenReaderText: `${formatMinuteGranularity(now, { timeZone, hour12 })} ${label}`,
  };
}

/** The first render, before the client's first tick. Matches the prototype's initial markup. */
export const CLOCK_PLACEHOLDER = "--:--:--";
