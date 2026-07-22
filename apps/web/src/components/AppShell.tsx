"use client";

/**
 * The application shell — PORTAL_SHELL_SPEC.md §2, §3, §4, §5.
 *
 * Landmark structure (§3): skip links first in the DOM, then `banner`, `navigation`, `main`,
 * and exactly two app-wide live regions — one polite (`status`) for route changes, saves and
 * presence-state changes, one assertive (`alert`) for ERRORS ONLY. A region that speaks for
 * routine events trains people to ignore it.
 *
 * DOM order IS visual order at every breakpoint (§11.1), which is why the header markup is not
 * reordered per breakpoint and why nothing here uses `order` or `row-reverse`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { JSX, ReactNode } from "react";
import { usePathname } from "next/navigation";
import { PrimaryNav } from "@sunil/ui";
import type { NavGroup } from "@sunil/ui";
import { HeaderClock } from "./HeaderClock";
import { SystemStatusPill } from "./SystemStatusPill";
import { UserMenu } from "./UserMenu";

/** One `<h1>` per page, and it lives in the header (§4, slot 2). */
const PAGE_TITLES: Readonly<Record<string, string>> = {
  "/": "Dashboard",
  "/settings": "Settings",
  "/system-health": "System Health",
};

function titleFor(pathname: string): string {
  return PAGE_TITLES[pathname] ?? "SUNIL";
}

export interface AppShellProps {
  groups: readonly NavGroup[];
  displayName: string;
  roleLabel: string;
  csrfToken?: string;
  /** True when `GET /auth/me` could not be reached and the nav is showing the §13 fallback. */
  limited?: boolean;
  children: ReactNode;
}

export function AppShell({
  groups,
  displayName,
  roleLabel,
  csrfToken,
  limited = false,
  children,
}: AppShellProps): JSX.Element {
  const pathname = usePathname() ?? "/";
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [polite, setPolite] = useState("");
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const navRef = useRef<HTMLElement | null>(null);
  const title = titleFor(pathname);

  const announce = useCallback((message: string) => {
    setPolite(message);
  }, []);

  // Route change: announce the destination by name (§11.2, §3).
  useEffect(() => {
    setPolite(`${titleFor(pathname)}.`);
    setDrawerOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (limited) setPolite("Navigation limited.");
  }, [limited]);

  // Drawer: Escape closes, focus returns to the toggle, body scroll is locked while open
  // (§5.6). Focus is trapped ONLY here and in modals (§11.2).
  useEffect(() => {
    if (!drawerOpen) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        setDrawerOpen(false);
        toggleRef.current?.focus();
        return;
      }
      if (event.key !== "Tab" || !navRef.current) return;
      const focusable = navRef.current.querySelectorAll<HTMLElement>("a[href], button");
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    navRef.current?.querySelector<HTMLElement>("a[href]")?.focus();
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [drawerOpen]);

  return (
    <>
      <a className="sunil-skip-link sunil-type-body-sm" href="#main">
        Skip to main content
      </a>
      <a className="sunil-skip-link sunil-type-body-sm" href="#primary-nav">
        Skip to navigation
      </a>

      <div className="sunil-ambience sunil-scanlines" aria-hidden="true" />

      <div className="sunil-shell">
        <header className="sunil-shell__header">
          <button
            ref={toggleRef}
            type="button"
            className="sunil-drawer-toggle"
            aria-expanded={drawerOpen}
            aria-controls="primary-nav"
            aria-label={drawerOpen ? "Close navigation" : "Open navigation"}
            onClick={() => {
              setDrawerOpen((value) => !value);
            }}
          >
            <span aria-hidden="true">☰</span>
          </button>

          <h1 id="page-title" className="sunil-page-title sunil-type-title" title={title}>
            {title}
          </h1>

          <div className="sunil-shell__spacer" />

          <SystemStatusPill onAnnounce={announce} />
          <HeaderClock />
          <UserMenu displayName={displayName} roleLabel={roleLabel} csrfToken={csrfToken} />
        </header>

        <PrimaryNav
            navRef={navRef}
            groups={groups}
            currentPath={pathname}
            limited={limited}
            className={drawerOpen ? "sunil-shell__nav--open" : undefined}
            brand={
              <div className="sunil-nav__brand">
                <span className="sunil-type-eyebrow">S.U.N.I.L</span>
                <span className="sunil-nav__brand-rule" aria-hidden="true" />
              </div>
            }
            footer={
              <div className="sunil-nav__footer">
                <span className="sunil-type-body-sm sunil-fg-primary">{displayName}</span>
                <span className="sunil-type-micro sunil-fg-muted sunil-nav__footer-detail">
                  {roleLabel}
                </span>
              </div>
            }
            onNavigate={() => {
              setDrawerOpen(false);
            }}
          />

        {drawerOpen ? (
          <button
            type="button"
            className="sunil-drawer-backdrop"
            aria-label="Close navigation"
            onClick={() => {
              setDrawerOpen(false);
              toggleRef.current?.focus();
            }}
          />
        ) : null}

        <main
          id="main"
          className="sunil-shell__main sunil-main"
          tabIndex={-1}
          aria-labelledby="page-title"
        >
          <div className="sunil-shell__content">{children}</div>
        </main>

        <div id="live-polite" role="status" aria-live="polite" className="sunil-sr-only">
          {polite}
        </div>
        {/* Errors only. Never used for anything routine (§3). */}
        <div id="live-alert" role="alert" aria-live="assertive" className="sunil-sr-only" />
      </div>
    </>
  );
}
