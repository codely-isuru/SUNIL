/**
 * Time-zone resolution and formatting — PORTAL_SHELL_SPEC.md §6.
 *
 * THE DEFECT BEING CLOSED. `prototype/sunil-command-centre.html` line 199 hard-codes
 * `timeZone:'Australia/Melbourne'`. The owner operates on `Australia/Hobart`. The two share an
 * offset for most of the year, which is exactly why the bug would survive casual testing and
 * then be wrong during the DST transition weeks and in every exported timestamp. It also
 * prints the literal string `MELBOURNE · AEST`, and Hobart is AEDT for part of the year.
 *
 * The rules, implemented here once so no page can get them wrong:
 *   1. Nothing formats a date without an explicit `timeZone`, and that zone always comes from
 *      the resolved setting. (`no-restricted-syntax` in this workspace's ESLint config makes a
 *      `toLocaleTimeString`/`toLocaleDateString`/`toLocaleString` call without a `timeZone`
 *      property a lint error, so the rule is enforced rather than trusted.)
 *   2. Resolution order: user preference → system setting → environment default →
 *      `DEFAULT_TIMEZONE`, which is a constant in ONE module, exported once.
 *   3. The browser's zone is never used silently. Settings offers an explicit
 *      "Use this device's time zone" option, and choosing it stores the resolved IANA name.
 *   4. Storage is always UTC; formatting happens at the edge.
 *   5. The zone abbreviation is DERIVED, never hard-coded.
 *   6. Every rendered timestamp can carry the full ISO 8601 value with offset in `title`.
 */

/** The final fallback. One constant, one module (§6.2). */
export const DEFAULT_TIMEZONE = "Australia/Hobart";

/** A-13: en-AU only in Phase 1. */
export const DEFAULT_LOCALE = "en-AU";

export interface TimeZoneSources {
  /** `user.settings.timezone` from `GET /api/auth/me`. */
  readonly user?: string | null | undefined;
  /** `system_settings['regional.timezone']`. */
  readonly system?: string | null | undefined;
  /** Environment default, e.g. `NEXT_PUBLIC_DEFAULT_TIMEZONE`. */
  readonly environment?: string | null | undefined;
}

/** Is this a zone the platform's ICU data actually knows? */
export function isValidTimeZone(zone: string | null | undefined): zone is string {
  if (typeof zone !== "string" || zone.trim() === "") return false;
  try {
    new Intl.DateTimeFormat(DEFAULT_LOCALE, { timeZone: zone }).format(new Date(0));
    return true;
  } catch {
    return false;
  }
}

/**
 * Resolve the zone in the order the spec mandates. An invalid value at any level is skipped
 * rather than thrown on: §13 requires the clock to fall back to `DEFAULT_TIMEZONE`, show it and
 * log — never to render blank.
 */
export function resolveTimeZone(sources: TimeZoneSources = {}): string {
  for (const candidate of [sources.user, sources.system, sources.environment]) {
    if (isValidTimeZone(candidate)) return candidate;
  }
  return DEFAULT_TIMEZONE;
}

/** The device's zone, only ever offered as an explicit choice (§6.3). */
export function detectDeviceTimeZone(): string {
  try {
    const detected = new Intl.DateTimeFormat().resolvedOptions().timeZone;
    return isValidTimeZone(detected) ? detected : DEFAULT_TIMEZONE;
  } catch {
    return DEFAULT_TIMEZONE;
  }
}

export interface TimeFormatOptions {
  readonly timeZone: string;
  readonly locale?: string;
  /** 24-hour is the Phase 1 default — the prototype's `hour12:false` (§9, Regional). */
  readonly hour12?: boolean;
  readonly seconds?: boolean;
}

function parts(date: Date, options: Intl.DateTimeFormatOptions, locale: string): Map<string, string> {
  const map = new Map<string, string>();
  for (const part of new Intl.DateTimeFormat(locale, options).formatToParts(date)) {
    map.set(part.type, part.value);
  }
  return map;
}

/** `HH:MM:SS` in the resolved zone. */
export function formatClockTime(date: Date, options: TimeFormatOptions): string {
  const locale = options.locale ?? DEFAULT_LOCALE;
  return new Intl.DateTimeFormat(locale, {
    timeZone: options.timeZone,
    hour12: options.hour12 ?? false,
    hour: "2-digit",
    minute: "2-digit",
    ...(options.seconds === false ? {} : { second: "2-digit" }),
  }).format(date);
}

/** The date stamp beneath the clock, in the resolved zone. */
export function formatDateStamp(date: Date, options: TimeFormatOptions): string {
  const locale = options.locale ?? DEFAULT_LOCALE;
  return new Intl.DateTimeFormat(locale, {
    timeZone: options.timeZone,
    weekday: "short",
    day: "2-digit",
    month: "short",
    year: "numeric",
  }).format(date);
}

/**
 * The zone abbreviation for THIS INSTANT — `AEST` in winter, `AEDT` in summer. Derived, never
 * hard-coded: that is the whole of defect A-10's second half.
 */
export function zoneAbbreviation(date: Date, timeZone: string, locale = DEFAULT_LOCALE): string {
  const value = parts(date, { timeZone, timeZoneName: "short" }, locale).get("timeZoneName");
  return value ?? "";
}

/** The city, from the IANA identifier's last segment with underscores replaced (§6.5). */
export function zoneCity(timeZone: string): string {
  const segment = timeZone.split("/").pop() ?? timeZone;
  return segment.replace(/_/g, " ");
}

/** e.g. `HOBART · AEDT`. Upper-casing is the caller's type token, not baked in here. */
export function zoneLabel(date: Date, timeZone: string, locale = DEFAULT_LOCALE): string {
  const abbreviation = zoneAbbreviation(date, timeZone, locale);
  const city = zoneCity(timeZone);
  return abbreviation === "" ? city : `${city} · ${abbreviation}`;
}

/**
 * The unambiguous instant, for the `title` attribute of every rendered timestamp (§6.6):
 * ISO 8601 with the offset of the resolved zone, e.g. `2026-01-15T09:30:00+11:00`.
 */
export function isoWithOffset(date: Date, timeZone: string): string {
  const p = parts(
    date,
    {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
      timeZoneName: "longOffset",
    },
    "en-GB",
  );
  const year = p.get("year") ?? "0000";
  const month = p.get("month") ?? "01";
  const day = p.get("day") ?? "01";
  const hour = (p.get("hour") ?? "00") === "24" ? "00" : (p.get("hour") ?? "00");
  const minute = p.get("minute") ?? "00";
  const second = p.get("second") ?? "00";
  const raw = p.get("timeZoneName") ?? "GMT";
  const offset = raw === "GMT" ? "+00:00" : raw.replace("GMT", "");
  return `${year}-${month}-${day}T${hour}:${minute}:${second}${offset}`;
}

/**
 * The hour (0–23) at this instant in the given zone. Used for the dashboard greeting, which is
 * generated from the clock and the user's display name only (§8.3) — a time-of-day greeting
 * computed from the host's zone would say "Good evening" to someone at breakfast.
 */
export function zoneHour(date: Date, timeZone: string): number {
  const value = parts(date, { timeZone, hour: "2-digit", hour12: false }, "en-GB").get("hour");
  const hour = Number.parseInt(value ?? "0", 10);
  return Number.isFinite(hour) ? hour % 24 : 0;
}

/** Minute-granularity time for the clock's `.sr-only` sibling (§4.2). */
export function formatMinuteGranularity(date: Date, options: TimeFormatOptions): string {
  return formatClockTime(date, { ...options, seconds: false });
}

/** "Last checked 12 seconds ago" for System Health (§10.1). Terse, no library. */
export function formatRelativeTime(from: Date, to: Date): string {
  const seconds = Math.max(0, Math.round((to.getTime() - from.getTime()) / 1000));
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds} seconds ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  return `${hours} hour${hours === 1 ? "" : "s"} ago`;
}
