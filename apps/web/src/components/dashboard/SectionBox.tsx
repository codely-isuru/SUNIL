"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "@/components/ui/Icon";

/**
 * A dashboard section (§16.3): a native `<details>` whose `<summary>` is the
 * "box" the owner clicks to expand in place, with a real `<a>` inside the
 * summary row for `Open full view →`.
 *
 * Zero JS by design — activating a link inside a `<summary>` follows the link
 * without toggling, so "expand" and "navigate" coexist without script, and
 * `<summary>` brings its own keyboard semantics and expanded-state reporting
 * (§16.6). Defaults per render: hero open, everything else closed; no
 * persistence — the server-rendered default *is* the design.
 */
export function SectionBox({
  heading,
  atRest,
  fullViewHref,
  leading,
  children,
  open = false,
  hero = false,
}: {
  heading: string;
  /** The at-rest figures — readable without expanding (§A.6). */
  atRest: ReactNode;
  fullViewHref: string;
  /** The key figure / live dot / section icon at the left of the summary row. */
  leading?: ReactNode;
  children: ReactNode;
  open?: boolean;
  hero?: boolean;
}) {
  return (
    <details
      open={open}
      className={`group rounded-md border bg-surface bg-sheen-panel ${
        hero ? "tick mt-4 border-border-accent" : "border-border"
      }`}
    >
      <summary
        className={`flex cursor-pointer items-center gap-3 rounded-md px-4 py-3 hover:bg-surface-raised ${
          hero ? "min-h-[64px]" : "min-h-[48px]"
        } group-open:rounded-b-none group-open:border-b group-open:border-border`}
      >
        {leading}
        <span className="min-w-0">
          <span className="block font-display text-h2 font-bold uppercase tracking-h2 text-text-secondary">
            {heading}
          </span>
          <span className="block text-small text-text-muted">{atRest}</span>
        </span>
        <span className="ml-auto flex items-center gap-3.5 whitespace-nowrap">
          <Link
            href={fullViewHref}
            className="text-small font-semibold text-accent hover:text-accent-hover"
          >
            Open full view &rarr;
          </Link>
          <Icon
            name="chevron-right"
            className="text-text-muted transition-transform duration-200 ease-standard group-open:rotate-90"
          />
        </span>
      </summary>
      <div className="px-4 pb-3.5 pt-1.5">{children}</div>
    </details>
  );
}

/**
 * The live pulse (§16.4) — the dashboard's ONE moving element, rendered only
 * while ≥1 task is running, frozen to a static ring when the poll is stale (a
 * glow may only claim liveness that is real) and under reduced motion (the
 * global kill-switch in globals.css).
 */
export function LiveDot({ live, stale }: { live: boolean; stale: boolean }) {
  if (!live) {
    return (
      <span
        role="img"
        aria-label="Idle — nothing is running"
        className="h-2.5 w-2.5 shrink-0 rounded-full bg-transparent shadow-[0_0_0_1px_rgba(154,141,113,.6)]"
      />
    );
  }
  return (
    <span
      role="img"
      aria-label={
        stale
          ? "Agents were running at the last successful update"
          : "Live — agents are running now"
      }
      className={`h-2.5 w-2.5 shrink-0 rounded-full bg-accent ${
        stale ? "shadow-[0_0_0_1px_rgba(201,162,39,.5)]" : "animate-work-pulse"
      }`}
    />
  );
}

/** A compact list row inside an expanded section. */
export function SectionRow({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5 border-b border-border py-2.5 last:border-b-0">
      {children}
    </div>
  );
}
