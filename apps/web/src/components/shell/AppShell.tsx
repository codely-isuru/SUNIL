"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { NavBottomBar, NavRail } from "./NavRail";
import { TopBar, type Crumb } from "./TopBar";
import { ShellDataProvider } from "./ShellData";

/**
 * The shell (§1.3): skip link → rail → topbar → `<main>`.
 *
 * Two accessibility behaviours are owned here rather than by any view:
 *
 * - **focus on route change** — after a client-side navigation, focus moves to
 *   the new view's `<h1>` (`tabindex="-1"`) and the view name is announced in
 *   a polite live region. Without it a keyboard user activates a rail item and
 *   is left behind in the rail with no idea the page changed (§1.3).
 * - **one polite live region per page**, reused for route changes, the
 *   poll-stale transition and decision results (§12.2) — never one
 *   announcement per poll.
 */

export function AppShell({
  title,
  crumbs,
  children,
}: {
  /** The announced view name; each view still renders its own <h1>. */
  title: string;
  crumbs: Crumb[];
  children: ReactNode;
}) {
  const pathname = usePathname();
  const mainRef = useRef<HTMLElement>(null);
  const liveRef = useRef<HTMLDivElement>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    if (firstRender.current) {
      // On a cold load the browser's own focus is correct; only a client-side
      // route change needs the move.
      firstRender.current = false;
      return;
    }
    const heading = mainRef.current?.querySelector<HTMLElement>("h1");
    heading?.focus();
    if (liveRef.current) liveRef.current.textContent = title;
  }, [pathname, title]);

  return (
    <ShellDataProvider>
      <a
        href="#main"
        className="absolute left-[-9999px] top-0 z-50 rounded-md border border-accent bg-surface px-3 py-2 focus:left-2 focus:top-2"
      >
        Skip to main content
      </a>

      <div className="grid min-h-dvh md:grid-cols-[64px_1fr] xl:grid-cols-[88px_1fr]">
        <NavRail />
        <div className="min-w-0">
          <TopBar crumbs={crumbs} />
          <main
            id="main"
            ref={mainRef}
            tabIndex={-1}
            className="max-w-[1152px] px-4 pb-24 pt-5 md:px-8 md:pb-16 md:pt-6"
          >
            {children}
          </main>
        </div>
      </div>

      <NavBottomBar />

      <div ref={liveRef} aria-live="polite" className="sr-only" />
    </ShellDataProvider>
  );
}
