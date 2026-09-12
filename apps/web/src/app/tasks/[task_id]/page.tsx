"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { AppShell } from "@/components/shell/AppShell";
import { StatusPill } from "@/components/ui/StatusPill";
import { UntrustedText } from "@/components/ui/UntrustedText";
import {
  ComingWithApi,
  EmptyState,
  ErrorPanel,
  Panel,
  SectionHeading,
  SkeletonRows,
  ViewHeading,
} from "@/components/ui/primitives";
import { listTasks } from "@/lib/api";
import { useAsync, useTick } from "@/lib/usePoll";
import { clockTime, relativeFromNow } from "@/lib/time";
import { describe } from "@/app/page";

/**
 * Task detail (`/tasks/{id}`) — spec §8.1's detail route, at layout fidelity.
 * `status_events` needs `GET /api/v1/tasks/{id}` (§13.1) to be frozen; until
 * then this renders the row the list returns plus its real links, and says so.
 */
export default function TaskDetailPage() {
  const params = useParams<{ task_id: string }>();
  const id = params?.task_id ?? "";
  return (
    <AppShell title="Task" crumbs={[{ label: "Tasks", href: "/tasks" }, { label: id, mono: true }]}>
      <TaskDetailView id={id} />
    </AppShell>
  );
}

function TaskDetailView({ id }: { id: string }) {
  const now = useTick();
  const { data, error, loading, reload } = useAsync(() => listTasks({ limit: 200 }), [id]);
  const task = data?.tasks.find((t) => t.id === id);

  if (loading) return <SkeletonRows rows={4} columns={["140px", "1fr"]} />;
  if (error) {
    return <ErrorPanel headline="Couldn't load that task." detail={describe(error)} onRetry={reload} />;
  }
  if (!task) {
    return (
      <>
        <ViewHeading>Task</ViewHeading>
        <div className="mt-4">
          <EmptyState
            headline="No task with that id."
            line="Ids look like task-01JQ8Z…. Check the id, or browse the task list."
            actionLabel="Browse tasks"
            actionHref="/tasks"
            icon="list-checks"
          />
        </div>
      </>
    );
  }

  return (
    <>
      <ViewHeading>Task</ViewHeading>
      <div className="mt-4 grid gap-4">
        <Panel className="p-4" ticked>
          <div className="flex flex-wrap items-center gap-3">
            <StatusPill status={task.status} context="task" size="md" />
            <span className="font-mono text-data text-text-muted">{task.id}</span>
          </div>
          <div className="mt-3">
            <UntrustedText
              label="Objective — plan text, shown exactly as received"
              value={task.objective}
            />
          </div>
          <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1.5 text-cell md:grid-cols-[150px_1fr]">
            <dt className="text-micro font-semibold uppercase tracking-pill text-text-muted">Agent</dt>
            <dd className="m-0">{task.assigned_agent}</dd>
            <dt className="text-micro font-semibold uppercase tracking-pill text-text-muted">Started</dt>
            <dd className="m-0">
              {task.started_at
                ? `${relativeFromNow(task.started_at, now)} · ${clockTime(task.started_at)}`
                : "—"}
            </dd>
            {task.failure_kind ? (
              <>
                <dt className="text-micro font-semibold uppercase tracking-pill text-text-muted">
                  Outcome
                </dt>
                <dd className="m-0 font-mono text-data text-danger">{task.failure_kind}</dd>
              </>
            ) : null}
          </dl>
          <ul className="mt-3 grid list-none gap-2 p-0 text-cell">
            {task.approval_id ? (
              <li>
                <Link href={`/approvals/${task.approval_id}`}>The approval this parked on &rarr;</Link>
              </li>
            ) : null}
            <li>
              <Link href={`/chat/${task.conversation_id}`}>The conversation &rarr;</Link>
            </li>
            <li>
              <Link href={`/audit/${task.request_id}`} className="font-mono">
                {`trace ${task.request_id} `}&rarr;
              </Link>
            </li>
          </ul>
        </Panel>

        <section className="grid gap-2.5">
          <SectionHeading>Status history</SectionHeading>
          <ComingWithApi endpoint="GET /api/v1/tasks/{id} → status_events (spec §13.1)" />
        </section>
      </div>
    </>
  );
}
