"use client";

import Link from "next/link";
import { AppShell } from "@/components/shell/AppShell";
import { StatusPill } from "@/components/ui/StatusPill";
import {
  ComingWithApi,
  EmptyState,
  ErrorPanel,
  SkeletonRows,
  StatRail,
  Timestamp,
  ViewHeading,
  ViewSubhead,
} from "@/components/ui/primitives";
import { listAuditTurns } from "@/lib/api";
import { useAsync, useTick } from "@/lib/usePoll";
import { clockTime, relativeFromNow } from "@/lib/time";
import { describe } from "@/app/page";

/**
 * Audit index (`/audit`) — spec §10.1, mockup 05.
 *
 * A stage count other than 12 is itself a signal and is rendered `warning`
 * (§10.1) — the missing-stage case is information, never something to hide or
 * pad. The `request_id` box is the primary way in: the owner usually arrives
 * with an id from another view.
 */
export default function AuditPage() {
  return (
    <AppShell title="Audit browser" crumbs={[{ label: "Audit" }]}>
      <AuditIndexView />
    </AppShell>
  );
}

function AuditIndexView() {
  const now = useTick();
  const { data, error, loading, reload } = useAsync(() => listAuditTurns({ limit: 50 }));
  const turns = data?.turns ?? [];

  return (
    <>
      <ViewHeading>Audit</ViewHeading>
      <ViewSubhead>
        Every turn SUNIL took, in plain English. Arrive with a request id, or browse the recent
        ones.
      </ViewSubhead>

      <StatRail
        label="Audit summary"
        stats={[
          {
            figure: turns[0] ? clockTime(turns[0].started_at) : "—",
            caption: "Last turn",
            tone: "key",
          },
          {
            figure: String(turns.filter((t) => t.outcome === "failed").length),
            caption: "Failed · loaded page",
            tone: "danger",
          },
          {
            figure: String(turns.filter((t) => t.outcome === "parked").length),
            caption: "Parked · loaded page",
            tone: "warning",
          },
          {
            figure: String(turns.filter((t) => t.stage_count !== 12).length),
            caption: "Turns not at 12 stages",
          },
        ]}
      />

      <div className="mt-3.5 grid gap-4">
        {loading ? (
          <SkeletonRows />
        ) : error ? (
          <ErrorPanel
            headline="Couldn't load the audit index."
            detail={describe(error)}
            onRetry={reload}
          />
        ) : turns.length === 0 ? (
          <EmptyState
            headline="No activity recorded yet."
            line="Every chat turn and scheduled run writes a twelve-stage trace here."
            actionLabel="Go to chat →"
            actionHref="/chat"
            icon="file-search"
          />
        ) : (
          <table className="w-full border-collapse overflow-hidden rounded-md border border-border bg-surface bg-sheen-panel">
            <caption className="sr-only">{`Audit turns, ${turns.length} rows, newest first`}</caption>
            <thead>
              <tr>
                {["Request", "When", "Conversation", "Outcome", "Stages", "Agent"].map((heading, i) => (
                  <th
                    key={heading}
                    scope="col"
                    className={`border-b border-border bg-surface-raised px-3.5 py-2.5 text-left text-micro font-semibold uppercase tracking-micro text-text-muted ${
                      i === 5 ? "hidden lg:table-cell" : ""
                    }`}
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {turns.map((turn) => (
                <tr key={turn.request_id} className="align-top hover:bg-surface-raised">
                  <td className="border-b border-border px-3.5 py-3 text-cell">
                    <Link
                      href={`/audit/${turn.request_id}`}
                      aria-label={`Trace ${turn.request_id} — ${turn.outcome ?? "unknown outcome"} — ${turn.stage_count} stages`}
                      className="font-mono text-data"
                    >
                      {turn.request_id}
                    </Link>
                  </td>
                  <td className="border-b border-border px-3.5 py-3 text-cell">
                    <Timestamp
                      iso={turn.started_at}
                      relative={relativeFromNow(turn.started_at, now)}
                      absolute={clockTime(turn.started_at)}
                    />
                  </td>
                  <td className="max-w-[34ch] truncate border-b border-border px-3.5 py-3 text-cell">
                    {turn.conversation_label ?? "—"}
                  </td>
                  <td className="border-b border-border px-3.5 py-3 text-cell">
                    {turn.outcome === "parked" ? (
                      <StatusPill status="parked" context="task" />
                    ) : turn.outcome === "failed" ? (
                      <StatusPill status="failed" context="task" label={turn.failure_kind ?? "Failed"} />
                    ) : (
                      <StatusPill status="completed" context="task" label="Ok" />
                    )}
                  </td>
                  <td
                    className={`border-b border-border px-3.5 py-3 font-mono text-data ${
                      turn.stage_count === 12 ? "text-text-muted" : "text-warning"
                    }`}
                  >
                    {`${turn.stage_count} / 12`}
                  </td>
                  <td className="hidden border-b border-border px-3.5 py-3 text-cell lg:table-cell">
                    {turn.agent ?? "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <ComingWithApi endpoint="GET /api/v1/audit (spec §13.3)" />
      </div>
    </>
  );
}
