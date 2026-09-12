"use client";

import Link from "next/link";
import { AppShell } from "@/components/shell/AppShell";
import { useShellData } from "@/components/shell/ShellData";
import { Icon } from "@/components/ui/Icon";
import { StatusPill } from "@/components/ui/StatusPill";
import { UntrustedText } from "@/components/ui/UntrustedText";
import {
  ComingWithApi,
  EmptyState,
  ErrorPanel,
  Panel,
  SectionHeading,
  SkeletonRows,
  StaleBanner,
  StatRail,
  ViewHeading,
  ViewSubhead,
} from "@/components/ui/primitives";
import { getActivity } from "@/lib/api";
import { usePoll, useTick } from "@/lib/usePoll";
import { clockTime, elapsedSince, relativeFromNow } from "@/lib/time";
import type { ActivityItem, StageName } from "@/lib/types";
import { describe } from "@/app/page";

/**
 * Agent activity (`/activity`) — spec §7, mockup 03. Real layout and all five
 * states against the §13.2 shape; the data source flips at integration (Q1).
 *
 * §7.3: the freshness chip is **mandatory** on this view and the elapsed
 * counters freeze while the poll is failing — an activity view showing a
 * 40-second-old "running" card without saying so is a lie about liveness.
 */

/** The 12→4 phase map (M1_CHAT_SPEC.md §5.3), reused not re-derived. */
const STAGE_TO_PHASE: Record<StageName, string> = {
  message_received: "Understanding",
  context_loaded: "Understanding",
  memory_retrieved: "Understanding",
  model_selected: "Understanding",
  llm_io: "Understanding",
  plan_created: "Planning",
  agent_started: "Working",
  tool_requested: "Working",
  permission_decision: "Working",
  tool_result: "Working",
  agent_result: "Finishing",
  final_response: "Finishing",
};

export default function ActivityPage() {
  return (
    <AppShell title="Agent activity" crumbs={[{ label: "Activity" }]}>
      <ActivityView />
    </AppShell>
  );
}

function ActivityView() {
  const live = useTick(1_000);
  const { stale } = useShellData();
  const poll = usePoll(() => getActivity());
  // Frozen clock while stale (§7.3) — the counters stop and grey rather than
  // ticking on data that is no longer being refreshed.
  const now = stale && poll.lastSuccessAt !== null ? poll.lastSuccessAt : live;

  const running = poll.data?.running ?? [];
  const parked = poll.data?.parked ?? [];
  const recent = poll.data?.recent ?? [];

  return (
    <>
      <ViewHeading>Agent activity</ViewHeading>
      <ViewSubhead>What SUNIL is doing right now, and what it just did.</ViewSubhead>

      <StatRail
        label="Activity summary"
        stats={[
          { figure: String(running.length), caption: "Running now", tone: "key" },
          { figure: String(parked.length), caption: "Waiting on you", tone: "warning" },
          {
            figure: String(recent.filter((t) => t.status === "failed").length),
            caption: "Failed today",
            tone: "danger",
          },
          {
            figure: String(recent.filter((t) => t.status === "completed").length),
            caption: "Finished today",
          },
        ]}
      />

      <div className="mt-3.5 grid gap-4">
        {stale ? (
          <StaleBanner>
            Elapsed counters are frozen at the last successful update — nothing here is live right
            now.
          </StaleBanner>
        ) : null}

        {poll.loading ? (
          <SkeletonRows rows={3} columns={["120px", "1fr", "90px"]} />
        ) : poll.error && !poll.data ? (
          <ErrorPanel
            headline="Couldn't load agent activity."
            detail={describe(poll.error)}
            onRetry={poll.refresh}
          />
        ) : running.length === 0 && parked.length === 0 && recent.length === 0 ? (
          <EmptyState
            headline="SUNIL is idle."
            line="Nothing is running. Scheduled workflows and your chat messages both show up here while they work."
            actionLabel="Ask SUNIL something →"
            actionHref="/chat"
            icon="activity"
          />
        ) : (
          <>
            <section className="grid gap-2.5">
              <SectionHeading>Now</SectionHeading>
              {running.length === 0 ? (
                <p className="text-small text-text-muted">
                  Nothing is running. SUNIL is idle right now.
                </p>
              ) : (
                running.map((item, index) => (
                  <RunningCard
                    key={item.id}
                    item={item}
                    now={now}
                    stale={stale}
                    ticked={index === 0}
                  />
                ))
              )}
            </section>

            <section className="grid gap-2.5">
              <SectionHeading>Waiting on you</SectionHeading>
              {parked.length === 0 ? (
                <p className="text-small text-text-muted">Nothing is parked for a decision.</p>
              ) : (
                parked.map((item) => (
                  <Panel key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                    <StatusPill status="parked" context="task" />
                    <span className="min-w-0 flex-1">
                      <UntrustedText value={item.objective} compact />
                    </span>
                    <span className="font-mono text-data text-text-muted">
                      {relativeFromNow(item.created_at, now)}
                    </span>
                    {item.approval_id ? (
                      <Link href={`/approvals/${item.approval_id}`} className="text-cell font-semibold">
                        Review and decide &rarr;
                      </Link>
                    ) : null}
                  </Panel>
                ))
              )}
            </section>

            <section className="grid gap-2.5">
              <SectionHeading>Recently finished</SectionHeading>
              {recent.map((item) => (
                <Panel key={item.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <StatusPill status={item.status} context="task" />
                  <span className="min-w-0 flex-1">
                    <UntrustedText value={item.objective} compact />
                  </span>
                  {item.failure_kind ? (
                    <span className="font-mono text-data text-danger">{item.failure_kind}</span>
                  ) : null}
                  <span className="font-mono text-data text-text-muted">
                    {item.completed_at ? clockTime(item.completed_at) : "—"}
                  </span>
                  <Link href={`/audit/${item.request_id}`} className="font-mono text-data">
                    {item.request_id}
                  </Link>
                </Panel>
              ))}
            </section>
          </>
        )}

        <ComingWithApi endpoint="GET /api/v1/activity (spec §13.2)" />
      </div>
    </>
  );
}

function RunningCard({
  item,
  now,
  stale,
  ticked,
}: {
  item: ActivityItem;
  now: number;
  stale: boolean;
  ticked: boolean;
}) {
  const phase = item.latest_stage ? STAGE_TO_PHASE[item.latest_stage as StageName] : "Working";
  return (
    <div
      role="status"
      className={`flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface bg-sheen-panel px-4 py-3.5 ${
        ticked ? "tick" : ""
      } ${stale ? "shadow-[0_0_0_1px_rgba(201,162,39,.5)]" : "animate-work-pulse"}`}
    >
      <Icon name="loader" className="text-accent" />
      <span className="min-w-0 flex-1">
        <b className="text-text-secondary">
          {item.latest_detail?.project_display_name
            ? `Checking ${item.latest_detail.project_display_name}…`
            : "Working…"}
        </b>
        <span className="block text-small text-text-muted">
          {`${item.assigned_agent} · ${phase}`}
          {item.latest_detail?.tool ? ` · ${item.latest_detail.tool}` : ""}
        </span>
      </span>
      <span className="font-mono text-data text-text-muted">
        {item.started_at ? elapsedSince(item.started_at, now) : "—"}
      </span>
      <Link href={`/audit/${item.request_id}`} className="text-cell font-semibold">
        Open trace &rarr;
      </Link>
    </div>
  );
}
