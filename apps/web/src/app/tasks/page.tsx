"use client";

import Link from "next/link";
import { AppShell } from "@/components/shell/AppShell";
import { StatusPill, rowEdgeClass } from "@/components/ui/StatusPill";
import { UntrustedText } from "@/components/ui/UntrustedText";
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
import { listTasks } from "@/lib/api";
import { useAsync, useTick } from "@/lib/usePoll";
import { clockTime, elapsedSince, relativeFromNow } from "@/lib/time";
import { describe } from "@/app/page";

/**
 * Tasks (`/tasks`) — spec §8, mockup 04. Real table, real states, §13.1 shape.
 *
 * Q2 is unresolved (`tasks` has no `project_key` column; the project lives in
 * `plan_created.detail`). Per the spec's default the Project column renders
 * only where the field is present and the project **filter is hidden** — the
 * view does not invent a filter the API cannot honour.
 */
export default function TasksPage() {
  return (
    <AppShell title="Tasks" crumbs={[{ label: "Tasks" }]}>
      <TasksView />
    </AppShell>
  );
}

function TasksView() {
  const now = useTick();
  const { data, error, loading, reload } = useAsync(() => listTasks({ limit: 50 }));
  const rows = data?.tasks ?? [];

  return (
    <>
      <ViewHeading>Tasks</ViewHeading>
      <ViewSubhead>
        A task is created whenever SUNIL makes a plan. Objectives are plan text — shown exactly as
        received.
      </ViewSubhead>

      <StatRail
        label="Task summary"
        stats={[
          {
            figure: String(
              rows.filter((t) => t.status === "in_progress" || t.status === "parked").length,
            ),
            caption: "In flight",
            tone: "key",
          },
          {
            figure: String(rows.filter((t) => t.status === "failed").length),
            caption: "Failed · loaded page",
            tone: "danger",
          },
          {
            figure: String(rows.filter((t) => t.status === "completed").length),
            caption: "Completed · loaded page",
          },
          { figure: String(rows.length), caption: "Rows loaded" },
        ]}
      />

      <div className="mt-3.5 grid gap-4">
        {loading ? (
          <SkeletonRows />
        ) : error ? (
          <ErrorPanel
            headline="Couldn't load tasks."
            detail={describe(error)}
            onRetry={reload}
          />
        ) : rows.length === 0 ? (
          <EmptyState
            headline="No tasks yet."
            line="A task is created whenever SUNIL makes a plan. Start a conversation and one will appear here."
            actionLabel="Go to chat →"
            actionHref="/chat"
            icon="list-checks"
          />
        ) : (
          <table className="w-full border-collapse overflow-hidden rounded-md border border-border bg-surface bg-sheen-panel">
            <caption className="sr-only">{`Tasks, ${rows.length} rows, newest first`}</caption>
            <thead>
              <tr>
                {["Status", "Objective", "Agent", "Project", "Started", "Duration", "Outcome", "Trace"].map(
                  (heading, index) => (
                    <th
                      key={heading}
                      scope="col"
                      className={`border-b border-border bg-surface-raised px-3.5 py-2.5 text-left text-micro font-semibold uppercase tracking-micro text-text-muted ${
                        index >= 5 ? "hidden lg:table-cell" : index === 3 ? "hidden md:table-cell" : ""
                      }`}
                    >
                      {heading}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {rows.map((task) => (
                <tr key={task.id} className="align-top hover:bg-surface-raised">
                  <td
                    className={`border-b border-border px-3.5 py-3 text-cell ${rowEdgeClass(task.status, "task")}`}
                  >
                    <StatusPill status={task.status} context="task" />
                  </td>
                  <td className="max-w-[44ch] border-b border-border px-3.5 py-3 text-cell">
                    <Link href={`/tasks/${task.id}`} aria-label={`${task.status} — ${task.objective}`}>
                      <span className="sr-only">Open task</span>
                    </Link>
                    <UntrustedText value={task.objective} compact />
                  </td>
                  <td className="border-b border-border px-3.5 py-3 text-cell">
                    {task.assigned_agent}
                  </td>
                  <td className="hidden border-b border-border px-3.5 py-3 font-mono text-data text-text-muted md:table-cell">
                    {task.project_key ?? "—"}
                  </td>
                  <td className="border-b border-border px-3.5 py-3 text-cell">
                    <Timestamp
                      iso={task.started_at ?? task.created_at}
                      relative={relativeFromNow(task.started_at ?? task.created_at, now)}
                      absolute={clockTime(task.started_at ?? task.created_at)}
                    />
                  </td>
                  <td className="hidden border-b border-border px-3.5 py-3 font-mono text-data lg:table-cell">
                    {task.completed_at && task.started_at
                      ? elapsedSince(task.started_at, Date.parse(task.completed_at))
                      : task.started_at
                        ? elapsedSince(task.started_at, now)
                        : "—"}
                  </td>
                  <td className="hidden border-b border-border px-3.5 py-3 text-cell lg:table-cell">
                    {task.failure_kind ? (
                      <span className="font-mono text-data text-danger">{task.failure_kind}</span>
                    ) : (
                      <span className="text-text-muted">—</span>
                    )}
                  </td>
                  <td className="hidden border-b border-border px-3.5 py-3 text-cell lg:table-cell">
                    <Link href={`/audit/${task.request_id}`} className="font-mono text-data">
                      {task.request_id}
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <ComingWithApi endpoint="GET /api/v1/tasks (spec §13.1)" />
      </div>
    </>
  );
}
