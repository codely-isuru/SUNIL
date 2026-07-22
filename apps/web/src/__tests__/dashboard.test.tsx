/**
 * The dashboard is HONEST-EMPTY — PORTAL_SHELL_SPEC.md §8, A-09, NFR-019,
 * architectural rule 7.
 *
 * §8.7 lists exactly what must not appear. This test is that list, inverted: it fails if
 * anybody reintroduces the prototype's fabricated dashboard, which is by far the most likely
 * "improvement" a future contributor will make to this screen.
 */
import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: () => undefined, replace: () => undefined }),
}));

const { default: DashboardPage } = await import("../app/(portal)/page");
const { TimeZoneProvider } = await import("../lib/time/TimeZoneProvider");

const html = renderToStaticMarkup(
  <TimeZoneProvider initialTimeZone="Australia/Hobart">
    <DashboardPage />
  </TimeZoneProvider>,
);

function countOf(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

describe("the permanent phase banner (§8.2)", () => {
  it("states the phase, what works, and that no business data is connected", () => {
    expect(html).toContain("Phase 1 — Foundation.");
    expect(html).toContain("has no assistant features yet");
    expect(html).toContain("No business data is connected.");
  });

  it("offers no way to dismiss it — a banner the user can hide stops being true", () => {
    expect(html).not.toContain("Dismiss");
    expect(html).not.toContain("aria-label=\"Close\"");
  });
});

describe("§8.7 — what must NOT appear", () => {
  it("reproduces none of the prototype's fabricated metrics", () => {
    for (const fabricated of [
      "MRR",
      "SUBSCRIBERS",
      "AD SPEND",
      "TICKETS",
      "Monthly recurring",
      "Brief Me",
      "RevenueCat",
      "Metricool",
      "Meta Ads",
      "Gmail",
    ]) {
      expect(html).not.toContain(fabricated);
    }
  });

  it("contains no content queue and no priority task list", () => {
    expect(html).not.toContain("queue-item");
    expect(html).not.toContain("Priority tasks");
  });

  it("contains no chart", () => {
    expect(html).not.toContain("<canvas");
    expect(html).not.toContain("chart");
  });

  it("shows no number that is not sourced from the health endpoint", () => {
    // Visible TEXT only: strip the decorative SVG (whose coordinates are geometry, not data)
    // and then every tag, leaving what a reader actually sees.
    const text = html
      .replace(/<svg[\s\S]*?<\/svg>/g, "")
      .replace(/<[^>]+>/g, " ")
      .replace(/&[a-z]+;/g, " ");
    // The only digits a Phase 1 dashboard may show are phase numbers. Every other number on
    // this page would be fabricated, because the only live source is the health endpoint and
    // it has not answered yet.
    expect(text.replace(/Phase \d/g, "").match(/\d/g)).toBeNull();
  });
});

describe("what IS there (§8.4, §8.5, §8.6)", () => {
  it("renders the live platform-status panel in its loading state, not with fake values", () => {
    expect(html).toContain("Platform status");
    expect(html).toContain("Loading platform status");
    expect(html).toContain("sunil-skeleton");
    expect(html).not.toContain("ONLINE");
  });

  it("lists what is coming, using the same vocabulary as the nav", () => {
    expect(html).toContain("Not yet available");
    expect(html).toContain("SUNIL Chat");
    expect(countOf(html, "sunil-badge")).toBe(19);
  });

  it("points at the three things that do work", () => {
    expect(html).toContain('href="/settings"');
    expect(html).toContain('href="/system-health"');
    expect(html).toContain("Where to go next");
  });

  it("renders the presence block with the shell owning the announcement (§11.5)", () => {
    expect(html).toContain("STATE · IDLE");
    expect(html).toContain("SUNIL is idle.");
    expect(html).not.toContain('role="status"');
  });

  it("greets by name only — it asserts nothing about system state", () => {
    expect(html).not.toContain("All systems are operational");
  });

  it("uses <h2> for panel titles, since the page <h1> lives in the header (§3)", () => {
    expect(countOf(html, "<h1")).toBe(0);
    expect(countOf(html, "<h2")).toBeGreaterThan(0);
  });
});
