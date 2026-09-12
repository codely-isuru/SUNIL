"use client";

import Link from "next/link";
import { AppShell } from "@/components/shell/AppShell";
import {
  EmptyState,
  ErrorPanel,
  Panel,
  SkeletonRows,
  ViewHeading,
  ViewSubhead,
} from "@/components/ui/primitives";
import { listProjects } from "@/lib/api";
import { useAsync, useTick } from "@/lib/usePoll";
import { clockTime, relativeFromNow } from "@/lib/time";
import { describe } from "@/app/page";

/**
 * Projects (`/projects`) — spec §9, mockup 04.
 *
 * Projects are **static config** (`config/projects.yaml`, FR-107), so this is
 * a reference list, not a CRUD surface — and the page says so. An
 * editable-looking grid that cannot be edited is worse than an honest
 * read-only list.
 */
export default function ProjectsPage() {
  return (
    <AppShell title="Projects" crumbs={[{ label: "Projects" }]}>
      <ProjectsView />
    </AppShell>
  );
}

function ProjectsView() {
  const now = useTick();
  const { data, error, loading, reload } = useAsync(() => listProjects());
  const projects = data?.projects ?? [];

  return (
    <>
      <ViewHeading>Projects</ViewHeading>
      <ViewSubhead>
        Projects come from SUNIL&apos;s configuration. Add one by editing{" "}
        <span className="font-mono text-data text-text-primary">config/projects.yaml</span> and
        restarting.
      </ViewSubhead>

      <div className="mt-4 grid gap-3.5">
        {loading ? (
          <SkeletonRows rows={4} columns={["1fr", "160px"]} />
        ) : error ? (
          <ErrorPanel headline="Couldn't load projects." detail={describe(error)} onRetry={reload} />
        ) : projects.length === 0 ? (
          <EmptyState
            headline="No projects configured."
            line="SUNIL can only work on projects it knows about. Add them to config/projects.yaml."
            icon="folder"
          />
        ) : (
          <div className="grid gap-3.5 md:grid-cols-2">
            {projects.map((project) => (
              <Panel key={project.key} className="border-border-accent p-4">
                <p className="m-0 font-display text-h2 font-bold uppercase tracking-h2 text-text-secondary">
                  {project.display_name}
                </p>
                <p className="m-0 mt-1 font-mono text-data text-text-muted">{project.key}</p>
                <dl className="mt-3 grid grid-cols-[150px_1fr] gap-x-4 gap-y-1 text-cell">
                  <dt className="text-micro font-semibold uppercase tracking-pill text-text-muted">
                    Last touched
                  </dt>
                  <dd className="m-0">
                    {project.last_activity_at
                      ? `${relativeFromNow(project.last_activity_at, now)} · ${clockTime(project.last_activity_at)}`
                      : "—"}
                  </dd>
                  <dt className="text-micro font-semibold uppercase tracking-pill text-text-muted">
                    Open items
                  </dt>
                  <dd className="m-0 flex gap-3">
                    <Link href={`/tasks?project_key=${project.key}`}>
                      {`${project.open_tasks ?? 0} open tasks`}
                    </Link>
                    <Link href="/approvals?status=pending">
                      {`${project.pending_approvals ?? 0} pending approvals`}
                    </Link>
                  </dd>
                </dl>
              </Panel>
            ))}
          </div>
        )}
        <p className="text-small text-text-muted">
          Per-project counts need the task→project linkage flagged as spec Q2; until it lands the
          figures come from the ops-read fixture.
        </p>
      </div>
    </>
  );
}
