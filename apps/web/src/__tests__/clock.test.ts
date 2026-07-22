/**
 * The header clock renders from the RESOLVED SETTING, not from the host.
 *
 * PORTAL_SHELL_SPEC.md §6.8 names this as the single assertion that catches every regression
 * of the inherited `Australia/Melbourne` defect (A-10). The host's zone is deliberately moved
 * around underneath the assertions: if any formatter in the render path reached for the host
 * zone, at least one of these would change, and none of them may.
 */
import { afterAll, beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_TIMEZONE, resolveTimeZone } from "@sunil/ui";
import { CLOCK_PLACEHOLDER, clockView } from "../lib/time/clockView";

/** 15 January 2026, 00:00 UTC — inside Australian daylight saving. */
const SUMMER = new Date("2026-01-15T00:00:00Z");
/** 15 July 2026, 00:00 UTC — outside it. */
const WINTER = new Date("2026-07-15T00:00:00Z");

const originalTz = process.env.TZ;

function withHostZone<T>(zone: string, run: () => T): T {
  process.env.TZ = zone;
  try {
    return run();
  } finally {
    process.env.TZ = originalTz;
  }
}

afterAll(() => {
  process.env.TZ = originalTz;
});

beforeEach(() => {
  process.env.TZ = originalTz;
});

describe("the clock renders from the setting (§6, A-10)", () => {
  it("shows AEDT and an 11-hour offset for Australia/Hobart on a DST date", () => {
    const view = clockView(SUMMER, DEFAULT_TIMEZONE);
    expect(view.time).toBe("11:00:00");
    expect(view.zoneLabel).toBe("Hobart · AEDT");
    expect(view.isoTitle).toBe("2026-01-15T11:00:00+11:00");
  });

  it("shows AEST outside DST — the abbreviation is derived, never hard-coded", () => {
    expect(clockView(WINTER, DEFAULT_TIMEZONE).zoneLabel).toBe("Hobart · AEST");
  });

  it("is identical whatever the host machine's zone is", () => {
    const reference = clockView(SUMMER, DEFAULT_TIMEZONE);
    for (const hostZone of ["UTC", "America/New_York", "Europe/London", "Asia/Tokyo"]) {
      const view = withHostZone(hostZone, () => clockView(SUMMER, DEFAULT_TIMEZONE));
      expect(`${hostZone}: ${view.time} ${view.zoneLabel} ${view.isoTitle}`).toBe(
        `${hostZone}: ${reference.time} ${reference.zoneLabel} ${reference.isoTitle}`,
      );
    }
  });

  it("changes when the SETTING changes, and only then", () => {
    expect(clockView(SUMMER, "Australia/Perth").time).toBe("08:00:00");
    expect(clockView(SUMMER, "UTC").zoneLabel).toBe("UTC · UTC");
    expect(clockView(SUMMER, "Australia/Hobart").time).not.toBe(
      clockView(SUMMER, "Australia/Perth").time,
    );
  });

  it("reads the screen-reader sibling at minute granularity, never per second", () => {
    expect(clockView(SUMMER, DEFAULT_TIMEZONE).screenReaderText).toBe("11:00 Hobart · AEDT");
  });

  it("honours the 12-hour setting without losing the zone", () => {
    const view = clockView(new Date("2026-01-15T09:30:00Z"), DEFAULT_TIMEZONE, true);
    expect(view.time).toMatch(/8:30:00\s*pm/i);
    expect(view.zoneLabel).toBe("Hobart · AEDT");
  });

  it("starts at the prototype's placeholder so hydration cannot mismatch on a moving value", () => {
    expect(CLOCK_PLACEHOLDER).toBe("--:--:--");
  });

  it("falls back to Australia/Hobart, never to the device zone (§6.2, §6.3)", () => {
    expect(resolveTimeZone()).toBe("Australia/Hobart");
    const view = withHostZone("America/New_York", () =>
      clockView(SUMMER, resolveTimeZone({ user: null, system: null })),
    );
    expect(view.zoneLabel).toBe("Hobart · AEDT");
  });
});
