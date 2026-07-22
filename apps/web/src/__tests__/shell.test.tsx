/**
 * The shell's landmark, heading and navigation contract — PORTAL_SHELL_SPEC.md §3, §5, §11,
 * NFR-016.
 *
 * Rendered with React's real server renderer, so these assertions are about the DOM the
 * browser receives. No DOM environment (`jsdom`/`happy-dom`) or `@testing-library/react` is in
 * this repo's lockfile and installing one mid-wave is forbidden, so interaction behaviour
 * (drawer focus trap, menu keyboard handling) is NOT covered here and is recorded as an
 * outstanding need in the handover.
 */
import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { NAV_GROUPS, limitedGroups, visibleGroups } from "@sunil/ui";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: () => undefined, replace: () => undefined }),
}));

const { AppShell } = await import("../components/AppShell");
const { TimeZoneProvider } = await import("../lib/time/TimeZoneProvider");

function render(node: Parameters<typeof renderToStaticMarkup>[0]): string {
  return renderToStaticMarkup(node);
}

function countOf(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

function shell(options: { limited?: boolean; permissions?: readonly string[] } = {}): string {
  const groups = options.limited
    ? limitedGroups(NAV_GROUPS)
    : visibleGroups(NAV_GROUPS, options.permissions ?? ["settings:read"]);
  return render(
    <TimeZoneProvider initialTimeZone="Australia/Hobart">
      <AppShell
        groups={groups}
        displayName="Isuru"
        roleLabel="Owner"
        limited={options.limited ?? false}
      >
        <p>page content</p>
      </AppShell>
    </TimeZoneProvider>,
  );
}

describe("landmarks and headings (§3)", () => {
  const html = shell();

  it("puts both skip links first in the DOM", () => {
    const skipIndex = html.indexOf("Skip to main content");
    expect(skipIndex).toBeGreaterThanOrEqual(0);
    expect(skipIndex).toBeLessThan(html.indexOf("<header"));
    expect(html.indexOf("Skip to navigation")).toBeLessThan(html.indexOf("<header"));
  });

  it("renders banner, navigation and main, with the nav named", () => {
    expect(html).toContain("<header");
    expect(html).toContain('aria-label="Primary"');
    expect(html).toContain('<main id="main"');
  });

  it("has exactly one <h1>, and main is labelled by it", () => {
    expect(countOf(html, "<h1")).toBe(1);
    expect(html).toContain('id="page-title"');
    expect(html).toContain('aria-labelledby="page-title"');
  });

  it("makes main a programmatic focus target for the skip link", () => {
    expect(html).toContain('tabindex="-1"');
    expect(html).toContain('href="#main"');
    expect(html).toContain('href="#primary-nav"');
  });

  it("renders exactly two app-wide live regions: one polite, one for errors", () => {
    expect(countOf(html, 'id="live-polite"')).toBe(1);
    expect(countOf(html, 'id="live-alert"')).toBe(1);
    expect(html).toContain('role="status" aria-live="polite"');
    expect(html).toContain('role="alert" aria-live="assertive"');
  });

  it("marks every decorative layer aria-hidden", () => {
    expect(html).toContain('class="sunil-ambience sunil-scanlines" aria-hidden="true"');
  });
});

describe("navigation inside the shell (§5, FR-101, Q10)", () => {
  const html = shell();

  it("renders all 22 destinations", () => {
    expect(countOf(html, "sunil-nav__label")).toBe(22);
  });

  it("gives only the three live destinations a link, and never href=\"#\"", () => {
    expect(countOf(html, 'class="sunil-nav__item sunil-type-body-sm" href=')).toBe(3);
    expect(html).not.toContain('href="#"');
  });

  it("keeps the nineteen unavailable destinations out of the tab order", () => {
    expect(countOf(html, "sunil-nav__item--unavailable")).toBe(19);
    expect(countOf(html, "— not yet available")).toBe(19);
    // The only tabindex in the shell is main's programmatic -1.
    expect(countOf(html, "tabindex")).toBe(1);
    expect(html).not.toContain("aria-disabled");
  });

  it("marks the current destination", () => {
    expect(countOf(html, 'aria-current="page"')).toBe(1);
  });
});

describe("the §13 error state for the nav", () => {
  it("renders the unguarded Phase 1 destinations only, and says so", () => {
    const html = shell({ limited: true });
    expect(html).toContain("Navigation limited");
    expect(countOf(html, "sunil-nav__label")).toBe(2);
    expect(html).not.toContain("SUNIL Chat");
  });

  it("hides Settings from a session without settings:read (§5.5)", () => {
    const html = shell({ permissions: [] });
    expect(html).not.toContain(">Settings<");
    expect(countOf(html, "sunil-nav__label")).toBe(21);
  });
});

describe("the header (§4)", () => {
  const html = shell();

  it("labels the drawer toggle and wires aria-expanded / aria-controls", () => {
    expect(html).toContain('aria-label="Open navigation"');
    expect(html).toContain('aria-controls="primary-nav"');
    expect(html).toContain('aria-expanded="false"');
  });

  it("renders the clock placeholder on the server so hydration cannot mismatch", () => {
    expect(html).toContain("--:--:--");
    expect(html).toContain("Hobart");
  });

  it("never renders a colour-only status: the lamp always carries text", () => {
    expect(html).toContain("System status: checking");
  });
});

describe("NFR-019 — nothing implies a capability that does not exist", () => {
  const html = shell();

  it("never claims a Phase 2+ destination is available", () => {
    for (const forbidden of ["Coming soon", "Beta", "Preview", "Try it"]) {
      expect(html).not.toContain(forbidden);
    }
    expect(html).toContain("Phase 2");
  });
});
