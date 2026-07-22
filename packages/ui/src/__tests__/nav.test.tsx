/**
 * The navigation contract — PORTAL_SHELL_SPEC.md §5 and FR-101.
 *
 * The assertion the task singles out is "disabled nav items are not focusable", and it is
 * asserted three ways, because there are three separate ways to get it wrong: an `href="#"`,
 * a `<button disabled>`, and a stray `tabindex`. The markup is rendered with React's real
 * server renderer, so what is asserted is the DOM the browser receives.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { PrimaryNav } from "../nav/PrimaryNav.js";
import {
  NAV_DESTINATION_COUNT,
  NAV_GROUPS,
  limitedGroups,
  visibleGroups,
} from "../nav/destinations.js";

function render(node: Parameters<typeof renderToStaticMarkup>[0]): string {
  return renderToStaticMarkup(node);
}

function countOf(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

const ALL_PERMISSIONS = ["settings:read"];

describe("information architecture (§5.1, Gate 1 / Q10)", () => {
  it("shows all 22 destinations", () => {
    expect(NAV_DESTINATION_COUNT).toBe(22);
  });

  it("gives an href to exactly the three live nav destinations", () => {
    const withHref = NAV_GROUPS.flatMap((g) => g.items).filter((i) => i.href !== undefined);
    expect(withHref.map((i) => i.href)).toEqual(["/", "/settings", "/system-health"]);
  });

  it("badges every unavailable destination with the phase it arrives in", () => {
    const unavailable = NAV_GROUPS.flatMap((g) => g.items).filter((i) => i.href === undefined);
    expect(unavailable).toHaveLength(19);
    for (const item of unavailable) {
      expect(item.badge).toMatch(/^Phase [2-5]$/);
    }
  });
});

describe("rendered markup (§5.3, §5.4)", () => {
  const html = render(
    <PrimaryNav groups={visibleGroups(NAV_GROUPS, ALL_PERMISSIONS)} currentPath="/" />,
  );

  it("renders exactly three links and nineteen non-link items", () => {
    expect(countOf(html, "<a ")).toBe(3);
    expect(countOf(html, "sunil-nav__item--unavailable")).toBe(19);
  });

  it("NEVER emits href=\"#\" — FR-101, 'none linking to a broken page'", () => {
    expect(html).not.toContain('href="#"');
  });

  it("puts no disabled item in the tab order: no tabindex, no button, no aria-disabled", () => {
    expect(html).not.toContain("tabindex");
    expect(html).not.toContain("<button");
    expect(html).not.toContain("aria-disabled");
  });

  it("keeps every unavailable destination discoverable as text", () => {
    expect(countOf(html, "— not yet available")).toBe(19);
    expect(html).toContain("SUNIL Chat");
    expect(html).toContain("Phase 2");
    expect(html).toContain("Phase 5");
  });

  it("marks the current page with aria-current", () => {
    expect(countOf(html, 'aria-current="page"')).toBe(1);
    const settings = render(
      <PrimaryNav groups={visibleGroups(NAV_GROUPS, ALL_PERMISSIONS)} currentPath="/settings" />,
    );
    expect(settings).toContain('href="/settings" aria-current="page"');
  });

  it("names the navigation landmark", () => {
    expect(html).toContain('aria-label="Primary"');
    expect(html).toContain('id="primary-nav"');
  });
});

describe("permission-aware navigation (§5.5, FR-101)", () => {
  it("HIDES an item the user lacks permission for — it does not disable it", () => {
    const html = render(<PrimaryNav groups={visibleGroups(NAV_GROUPS, [])} currentPath="/" />);
    expect(html).not.toContain("Settings");
    // "Disabled" would say "coming in a later phase", which for a viewer would be a lie.
    expect(countOf(html, "<a ")).toBe(2);
  });

  it("hides a group whose every item is hidden", () => {
    const groups = visibleGroups(
      [{ id: "solo", label: "Solo", items: [NAV_GROUPS[4]?.items[4] ?? { id: "x", label: "x", icon: "settings", permission: "nope" }] }],
      [],
    );
    expect(groups).toHaveLength(0);
  });

  it("falls back to the unguarded Phase 1 destinations when permissions cannot be loaded", () => {
    const html = render(
      <PrimaryNav groups={limitedGroups(NAV_GROUPS)} currentPath="/" limited />,
    );
    expect(html).toContain("Navigation limited");
    expect(countOf(html, "<a ")).toBe(2);
    expect(html).toContain("Dashboard");
    expect(html).toContain("System Health");
    // Never render everything as a fallback.
    expect(html).not.toContain("SUNIL Chat");
  });
});
