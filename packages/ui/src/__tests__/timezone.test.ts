/**
 * PORTAL_SHELL_SPEC.md §6 — closing the inherited `Australia/Melbourne` defect (A-10).
 *
 * §6.8 names the single assertion that catches every regression of this bug: with the setting
 * at `Australia/Hobart` and the host clock in UTC, on a date inside Australian DST, the clock
 * must show `AEDT` and an 11-hour offset. That is the first test below.
 */
import { describe, expect, it } from "vitest";
import {
  DEFAULT_TIMEZONE,
  detectDeviceTimeZone,
  formatClockTime,
  formatDateStamp,
  formatMinuteGranularity,
  formatRelativeTime,
  isValidTimeZone,
  isoWithOffset,
  resolveTimeZone,
  zoneAbbreviation,
  zoneCity,
  zoneLabel,
} from "../time/timezone.js";

/** 15 January 2026, 00:00 UTC — inside Australian daylight saving. */
const SUMMER = new Date("2026-01-15T00:00:00Z");
/** 15 July 2026, 00:00 UTC — outside it. */
const WINTER = new Date("2026-07-15T00:00:00Z");

describe("the Melbourne defect (§6)", () => {
  it("renders AEDT and an 11-hour offset for Hobart on a DST date", () => {
    expect(zoneAbbreviation(SUMMER, DEFAULT_TIMEZONE)).toBe("AEDT");
    expect(isoWithOffset(SUMMER, DEFAULT_TIMEZONE)).toBe("2026-01-15T11:00:00+11:00");
    expect(formatClockTime(SUMMER, { timeZone: DEFAULT_TIMEZONE })).toBe("11:00:00");
  });

  it("renders AEST and a 10-hour offset for Hobart outside DST", () => {
    expect(zoneAbbreviation(WINTER, DEFAULT_TIMEZONE)).toBe("AEST");
    expect(isoWithOffset(WINTER, DEFAULT_TIMEZONE)).toBe("2026-07-15T10:00:00+10:00");
  });

  it("derives the label instead of printing the prototype's hard-coded string", () => {
    expect(zoneLabel(SUMMER, DEFAULT_TIMEZONE)).toBe("Hobart · AEDT");
    expect(zoneLabel(WINTER, DEFAULT_TIMEZONE)).toBe("Hobart · AEST");
    // The prototype printed this literal, for the wrong city, all year round.
    expect(zoneLabel(SUMMER, DEFAULT_TIMEZONE)).not.toBe("MELBOURNE · AEST");
  });

  it("distinguishes Hobart from Melbourne, which is why the bug survived testing", () => {
    // Same offset today...
    expect(isoWithOffset(SUMMER, "Australia/Melbourne")).toBe(isoWithOffset(SUMMER, DEFAULT_TIMEZONE));
    // ...but a different city, and the setting must carry the user's actual zone.
    expect(zoneCity("Australia/Melbourne")).toBe("Melbourne");
    expect(zoneCity(DEFAULT_TIMEZONE)).toBe("Hobart");
  });

  it("renders from the resolved SETTING, not from the host locale or zone", () => {
    // The host process runs in whatever zone the CI machine has. Every formatter here takes
    // an explicit timeZone, so the same instant renders differently per setting and identically
    // per setting regardless of the host.
    const hobart = formatClockTime(SUMMER, { timeZone: "Australia/Hobart" });
    const utc = formatClockTime(SUMMER, { timeZone: "UTC" });
    const perth = formatClockTime(SUMMER, { timeZone: "Australia/Perth" });
    expect(hobart).toBe("11:00:00");
    expect(utc).toBe("00:00:00");
    expect(perth).toBe("08:00:00");
    expect(new Set([hobart, utc, perth]).size).toBe(3);
  });

  it("uses 24-hour time by default — the prototype's hour12:false", () => {
    const evening = new Date("2026-01-15T09:30:00Z"); // 20:30 in Hobart
    expect(formatClockTime(evening, { timeZone: DEFAULT_TIMEZONE })).toBe("20:30:00");
    expect(formatClockTime(evening, { timeZone: DEFAULT_TIMEZONE, hour12: true })).toMatch(/pm/i);
  });

  it("gives a minute-granularity string for the clock's screen-reader sibling (§4.2)", () => {
    expect(formatMinuteGranularity(SUMMER, { timeZone: DEFAULT_TIMEZONE })).toBe("11:00");
  });

  it("formats the date stamp in the resolved zone", () => {
    expect(formatDateStamp(SUMMER, { timeZone: DEFAULT_TIMEZONE })).toContain("2026");
    expect(formatDateStamp(SUMMER, { timeZone: DEFAULT_TIMEZONE })).toContain("Jan");
  });
});

describe("resolution order (§6.2)", () => {
  it("prefers the user setting, then the system setting, then the environment", () => {
    expect(
      resolveTimeZone({ user: "Europe/London", system: "Australia/Perth", environment: "UTC" }),
    ).toBe("Europe/London");
    expect(resolveTimeZone({ system: "Australia/Perth", environment: "UTC" })).toBe(
      "Australia/Perth",
    );
    expect(resolveTimeZone({ environment: "UTC" })).toBe("UTC");
  });

  it("falls back to Australia/Hobart — the one constant, in one module", () => {
    expect(resolveTimeZone()).toBe("Australia/Hobart");
    expect(DEFAULT_TIMEZONE).toBe("Australia/Hobart");
  });

  it("skips an invalid zone rather than throwing, so the clock is never blank (§13)", () => {
    expect(resolveTimeZone({ user: "Mars/Olympus_Mons" })).toBe(DEFAULT_TIMEZONE);
    expect(resolveTimeZone({ user: "", system: null, environment: undefined })).toBe(
      DEFAULT_TIMEZONE,
    );
    expect(isValidTimeZone("Australia/Hobart")).toBe(true);
    expect(isValidTimeZone("Not/AZone")).toBe(false);
  });

  it("never uses the device zone silently — it is only ever an explicit choice (§6.3)", () => {
    // `detectDeviceTimeZone` exists for the Settings option and is not part of resolution.
    expect(isValidTimeZone(detectDeviceTimeZone())).toBe(true);
    expect(resolveTimeZone()).toBe(DEFAULT_TIMEZONE);
  });
});

describe("relative time (§10.1)", () => {
  it("reads as words, terse, no library", () => {
    const base = new Date("2026-01-15T00:00:00Z");
    expect(formatRelativeTime(base, new Date("2026-01-15T00:00:02Z"))).toBe("just now");
    expect(formatRelativeTime(base, new Date("2026-01-15T00:00:30Z"))).toBe("30 seconds ago");
    expect(formatRelativeTime(base, new Date("2026-01-15T00:01:00Z"))).toBe("1 minute ago");
    expect(formatRelativeTime(base, new Date("2026-01-15T02:00:00Z"))).toBe("2 hours ago");
  });
});
