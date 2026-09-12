"use client";

import Link from "next/link";
import { Icon } from "@/components/ui/Icon";
import { useShellData } from "./ShellData";

/**
 * Topbar (§1.3): wordmark, the active view's breadcrumb, the session
 * `StatusDot`, the pending chip and the §1.5 freshness indicator.
 */

export interface Crumb {
  label: string;
  href?: string;
  mono?: boolean;
}

const CHIP =
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-surface-raised px-2.5 py-1 text-micro font-semibold uppercase tracking-pill text-text-muted";

export function PollFreshness() {
  const { ageMs, stale, refresh } = useShellData();
  const seconds = ageMs === null ? null : Math.floor(ageMs / 1000);

  return (
    <button
      type="button"
      onClick={refresh}
      aria-label={
        seconds === null
          ? "Waiting for the first update. Refresh now."
          : `Last updated ${seconds} seconds ago. Refresh now.`
      }
      className={`${CHIP} ${stale ? "border-warning text-warning" : ""}`}
    >
      <Icon name={stale ? "alert-triangle" : "refresh"} size={14} />
      <span className="font-mono text-[0.6875rem]">
        {seconds === null ? "—" : stale ? `stale ${seconds}s` : `${seconds}s`}
      </span>
    </button>
  );
}

export function TopBar({ crumbs }: { crumbs: Crumb[] }) {
  const { pendingCount } = useShellData();

  return (
    <header className="sticky top-0 z-10 flex h-14 items-center gap-3.5 border-b border-border bg-surface px-4 md:px-6">
      <span className="font-display text-[0.8125rem] font-bold tracking-brand text-accent">
        S.U.N.I.L
      </span>

      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-2 text-small text-text-muted">
        {crumbs.map((crumb, index) => (
          <span key={`${crumb.label}-${index}`} className="flex min-w-0 items-center gap-2">
            <Icon name="chevron-right" size={14} />
            {crumb.href ? (
              <Link href={crumb.href} className="text-accent hover:text-accent-hover hover:underline">
                {crumb.label}
              </Link>
            ) : (
              <b
                className={`truncate font-semibold text-text-secondary ${crumb.mono ? "font-mono" : ""}`}
              >
                {crumb.label}
              </b>
            )}
          </span>
        ))}
      </nav>

      <span className="flex-1" />

      <span className={`${CHIP} hidden sm:inline-flex`}>
        <span className="h-2 w-2 shrink-0 rounded-full bg-success" />
        SUNIL online
      </span>

      {pendingCount > 0 ? (
        <Link href="/approvals" className={`${CHIP} border-warning text-warning hover:no-underline`}>
          <Icon name="clock" size={14} />
          {`${pendingCount} pending`}
        </Link>
      ) : null}

      <PollFreshness />
    </header>
  );
}
