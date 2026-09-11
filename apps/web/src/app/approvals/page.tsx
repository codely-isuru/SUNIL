"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { ExpiryMeter, OperationIdentifier } from "@/components/approvals/bits";
import { StatusPill, rowEdgeClass } from "@/components/ui/StatusPill";
import { UntrustedText } from "@/components/ui/UntrustedText";
import {
  Button,
  EmptyState,
  ErrorPanel,
  Panel,
  SkeletonRows,
  StaleBanner,
  StatRail,
  Timestamp,
  ViewHeading,
  ViewSubhead,
} from "@/components/ui/primitives";
import { listApprovals } from "@/lib/api";
import { usePoll, useTick } from "@/lib/usePoll";
import { clockTime, countdownTo, relativeFromNow, shortTime } from "@/lib/time";
import type { Approval, ApprovalStatus } from "@/lib/types";
import { describe } from "@/app/page";

/**
 * The approvals queue (`/approvals`) — spec §5, mockup 01.
 *
 * Two rules from the spec are visible in the markup and must stay:
 *
 * - **No Approve/Refuse buttons in the list** (Decision 4). A decision is
 *   irreversible, so it may only be made on a screen that shows the full
 *   params. A mis-tap in a list can never decide an approval.
 * - **One primary link per row**, in the Action cell, whose accessible name
 *   carries the whole row (§5.2). An `<a>` cannot wrap a `<tr>`, and a link
 *   per cell would give one row five focus stops; the row-level click is a
 *   mouse-only convenience on top of the real anchor.
 */

const FILTERS: { label: string; value: ApprovalStatus | "all" }[] = [
  { label: "Pending", value: "pending" },
  { label: "Approved", value: "approved" },
  { label: "Refused", value: "refused" },
  { label: "Expired", value: "expired" },
  { label: "Consumed", value: "consumed" },
  { label: "All", value: "all" },
];

export default function ApprovalsPage() {
  return (
    <AppShell title="Approvals queue" crumbs={[{ label: "Approvals" }]}>
      <Suspense fallback={<SkeletonRows />}>
        <ApprovalsQueue />
      </Suspense>
    </AppShell>
  );
}

function ApprovalsQueue() {
  const params = useSearchParams();
  const now = useTick();
  const status = (params?.get("status") ?? "pending") as ApprovalStatus | "all";

  const poll = usePoll(
    () => listApprovals(status === "all" ? { limit: 50 } : { status, limit: 50 }),
    // The filter is a URL query param (deep-linkable, back-restorable, §2 FilterBar).
    { intervalMs: 10_000 },
  );

  const rows = poll.data?.approvals ?? [];
  const pending = rows.filter((r) => r.status === "pending");
  const sorted =
    status === "all"
      ? [...rows].sort((a, b) => Number(b.status === "pending") - Number(a.status === "pending"))
      : rows;

  const nextExpiry = [...pending].sort(
    (a, b) => Date.parse(a.expires_at) - Date.parse(b.expires_at),
  )[0];
  const oldest = [...pending].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  )[0];
  const decided = rows.filter((r) => r.decided_at).length;
  const lastGoodAt =
    poll.ageMs !== null ? clockTime(new Date(Date.now() - poll.ageMs).toISOString()) : undefined;

  return (
    <>
      <ViewHeading>Approvals</ViewHeading>
      <ViewSubhead>
        {`${pending.length} waiting for you · ${decided} decided in the loaded page. `}
        Polled every 10s (C4 §2 — no push channel).
      </ViewSubhead>

      <StatRail
        label="Queue summary"
        stats={[
          { figure: String(pending.length), caption: "Pending — waiting on you", tone: "key" },
          {
            figure: nextExpiry ? countdownTo(nextExpiry.expires_at, now).figure : "—",
            caption: nextExpiry ? `Next expiry · ${nextExpiry.tool}` : "Next expiry",
            tone: nextExpiry && countdownTo(nextExpiry.expires_at, now).level === "danger" ? "danger" : "default",
          },
          {
            figure: oldest ? relativeFromNow(oldest.created_at, now).replace(" ago", "") : "—",
            caption: "Oldest wait",
          },
          { figure: String(decided), caption: "Decided · loaded page" },
        ]}
      />

      <div className="my-3.5 flex flex-wrap items-center gap-3">
        <div className="inline-flex overflow-hidden rounded-md border border-border bg-surface">
          {FILTERS.map((filter) => (
            <Link
              key={filter.value}
              href={`/approvals?status=${filter.value}`}
              aria-current={status === filter.value ? "true" : undefined}
              className={`border-r border-border px-3 py-1.5 text-small font-medium last:border-r-0 hover:bg-surface-raised hover:no-underline ${
                status === filter.value
                  ? "bg-surface-raised text-text-primary shadow-[inset_0_-2px_0_#C9A227]"
                  : "text-text-muted hover:text-text-secondary"
              }`}
            >
              {filter.label}
            </Link>
          ))}
        </div>
        <span className="flex-1" />
        <span className="text-micro font-semibold uppercase tracking-micro text-text-muted">
          Newest first
        </span>
      </div>

      {poll.stale ? (
        <StaleBanner lastGoodAt={lastGoodAt}>
          Decisions are disabled until this reconnects. This list may be out of date.
        </StaleBanner>
      ) : null}

      {poll.loading ? (
        <SkeletonRows />
      ) : poll.error && rows.length === 0 ? (
        <ErrorPanel
          headline="Couldn't load the approvals queue."
          detail={describe(poll.error)}
          onRetry={poll.refresh}
        />
      ) : rows.length === 0 ? (
        status === "pending" ? (
          <EmptyState
            headline="Nothing needs your approval."
            line="SUNIL parks a task here whenever a plan reaches an action it isn't allowed to take on its own. Nothing is waiting on you right now."
            actionLabel="View decided approvals"
            actionHref="/approvals?status=all"
          />
        ) : (
          <EmptyState
            headline={`No ${status} approvals.`}
            line="Nothing in the queue matches this filter."
            actionLabel="Clear filters"
            actionHref="/approvals?status=all"
          />
        )
      ) : (
        <>
          <div className="tick">
            <QueueTable rows={sorted} now={now} dimmed={poll.stale} />
          </div>
          <p className="mt-3.5 text-small text-text-muted">
            {poll.data?.next_cursor ? (
              <Button onClick={poll.refresh}>Load 50 more</Button>
            ) : (
              `End of list — ${rows.length} shown.`
            )}
          </p>
        </>
      )}
    </>
  );
}

function QueueTable({
  rows,
  now,
  dimmed,
}: {
  rows: Approval[];
  now: number;
  dimmed: boolean;
}) {
  return (
    <table
      className={`w-full border-collapse overflow-hidden rounded-md border border-border bg-surface bg-sheen-panel ${
        dimmed ? "opacity-85" : ""
      }`}
    >
      <caption className="sr-only">{`Approvals, ${rows.length} rows, newest first`}</caption>
      <thead>
        <tr>
          {["Status", "Action", "What it does (as received)", "Agent", "Requested", "Expires", "Task"].map(
            (heading, index) => (
              <th
                key={heading}
                scope="col"
                className={`border-b border-border bg-surface-raised px-3.5 py-2.5 text-left text-micro font-semibold uppercase tracking-micro text-text-muted ${
                  index === 3 || index === 6 ? "hidden lg:table-cell" : ""
                }`}
              >
                {heading}
              </th>
            ),
          )}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.id} className="align-top hover:bg-surface-raised">
            <td className={`border-b border-border px-3.5 py-3 text-cell ${rowEdgeClass(row.status)}`}>
              <StatusPill status={row.status} />
            </td>
            <td className="border-b border-border px-3.5 py-3 text-cell">
              <Link
                href={`/approvals/${row.id}`}
                aria-label={`${row.status} — ${row.tool}.${row.operation} — ${row.summary} — review and decide`}
                className="block text-text-primary hover:text-accent-hover"
              >
                <OperationIdentifier tool={row.tool} operation={row.operation} />
              </Link>
            </td>
            <td className="max-w-[46ch] border-b border-border px-3.5 py-3 text-cell">
              <UntrustedText value={row.summary} compact />
            </td>
            <td className="hidden border-b border-border px-3.5 py-3 text-cell lg:table-cell">
              {row.agent_id}
            </td>
            <td className="border-b border-border px-3.5 py-3 text-cell">
              <Timestamp
                iso={row.created_at}
                relative={relativeFromNow(row.created_at, now)}
                absolute={clockTime(row.created_at)}
              />
            </td>
            <td className="border-b border-border px-3.5 py-3 text-cell">
              {row.status === "pending" ? (
                <ExpiryMeter expiresAt={row.expires_at} now={now} showExpiringSuffix />
              ) : row.consumed_at ? (
                <span className="text-text-muted">{`executed ${shortTime(row.consumed_at)}`}</span>
              ) : row.decided_at ? (
                <span className="text-text-muted">
                  {`${row.status} ${shortTime(row.decided_at)}`}
                </span>
              ) : (
                <span className="text-text-muted">{`expired ${clockTime(row.expires_at)}`}</span>
              )}
            </td>
            <td className="hidden border-b border-border px-3.5 py-3 text-cell lg:table-cell">
              <Link href={`/tasks/${row.task_id}`} className="font-mono text-data">
                {row.task_id}
              </Link>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function QueuePanelFallback() {
  return <Panel className="p-4">Loading…</Panel>;
}
