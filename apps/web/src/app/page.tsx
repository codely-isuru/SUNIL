"use client";

import Link from "next/link";
import { AppShell } from "@/components/shell/AppShell";
import { useShellData } from "@/components/shell/ShellData";
import { LiveDot, SectionBox, SectionRow } from "@/components/dashboard/SectionBox";
import { ExpiryMeter, OperationIdentifier } from "@/components/approvals/bits";
import { Icon } from "@/components/ui/Icon";
import { StatusPill } from "@/components/ui/StatusPill";
import { UntrustedText } from "@/components/ui/UntrustedText";
import {
  EmptyState,
  ErrorPanel,
  Panel,
  SkeletonBlock,
  StaleBanner,
  ViewHeading,
  ViewSubhead,
} from "@/components/ui/primitives";
import { getActivity, listAuditTurns, listProjects, listTasks } from "@/lib/api";
import { useAsync, useTick } from "@/lib/usePoll";
import { clockTime, countdownTo, elapsedSince, relativeFromNow, shortTime } from "@/lib/time";
import type { Approval } from "@/lib/types";

/**
 * The Dashboard (`/`) — spec §16, mockup 00. The landing view, owner-ordered
 * at round 4.
 *
 * §16.1 is the rule that keeps it cheap: this is **not a sixth data model**.
 * Every section is the summary tier of an existing view, built from that
 * view's own components (`StatusPill`, `UntrustedText` compact form,
 * `ExpiryMeter`, the relative+absolute timestamp pattern) and its own query.
 * Nothing here may render a field its full view does not have, and there are
 * **no decision controls on this page** (Decision 4 — the dashboard shows,
 * the card decides).
 */

/** Hero ordering (§16.2): soonest expiry pressure first, then age. */
function byUrgency(a: Approval, b: Approval) {
  const ea = Date.parse(a.expires_at);
  const eb = Date.parse(b.expires_at);
  if (ea !== eb) return ea - eb;
  return Date.parse(a.created_at) - Date.parse(b.created_at);
}

export default function DashboardPage() {
  return (
    <AppShell title="Dashboard" crumbs={[{ label: "Dashboard" }]}>
      <DashboardView />
    </AppShell>
  );
}

function DashboardView() {
  const now = useTick();
  const { pending, pendingCount, stale, loading, error, lastSuccessAt, refresh } = useShellData();

  const activity = useAsync(() => getActivity());
  const tasks = useAsync(() => listTasks({ limit: 5 }));
  const projects = useAsync(() => listProjects());
  const audit = useAsync(() => listAuditTurns({ limit: 4 }));

  const hero = [...pending].sort(byUrgency);
  const top3 = hero.slice(0, 3);
  const nextExpiry = hero[0] ? countdownTo(hero[0].expires_at, now) : null;
  const oldest = [...pending].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  )[0];

  const running = activity.data?.running ?? [];
  const parked = activity.data?.parked ?? [];
  const finishedToday = activity.data?.recent.length ?? 0;

  const lastGoodAt =
    lastSuccessAt !== null ? clockTime(new Date(lastSuccessAt).toISOString()) : undefined;

  return (
    <>
      <ViewHeading>Dashboard</ViewHeading>
      <ViewSubhead>
        Everything in one place. Each box expands in place — or take its{" "}
        <span className="text-accent">open full view &rarr;</span> link to the page. Same 10s poll
        as everywhere else.
      </ViewSubhead>

      {stale ? (
        <div className="mt-4">
          <StaleBanner lastGoodAt={lastGoodAt}>
            Nothing on this page decides anything, so nothing is disabled here — the approval card
            blocks its own buttons until a poll succeeds.
          </StaleBanner>
        </div>
      ) : null}

      {/* 1 · Chat quick-entry — an affordance, honestly an <a> to /chat. No
          message is ever sent from the Dashboard (§16.2 rule 1). */}
      <Link
        href="/chat?focus=composer"
        aria-label="Ask SUNIL something — opens chat with the composer focused"
        className="mt-4 flex items-center gap-3 rounded-md border border-border bg-surface-high px-3.5 py-2.5 text-text-muted hover:border-border-strong hover:text-text-secondary hover:no-underline"
      >
        <Icon name="chat" />
        Ask SUNIL to check on something…
        <span className="ml-auto whitespace-nowrap text-cell font-semibold text-accent">
          Open chat &rarr;
        </span>
      </Link>

      {/* 2 · Hero — pending approvals. Ships open. */}
      {loading ? (
        <Panel className="mt-4 grid gap-3 px-4 py-3.5" ticked>
          <div aria-busy="true" className="grid gap-3">
            <SkeletonBlock width="38%" />
            <SkeletonBlock width="62%" />
            <SkeletonBlock width="47%" />
          </div>
        </Panel>
      ) : error && pendingCount === 0 ? (
        <div className="mt-4">
          <ErrorPanel
            headline="Couldn't load the approvals queue."
            detail={describe(error)}
            onRetry={refresh}
          />
        </div>
      ) : pendingCount === 0 ? (
        // All-quiet (§16.5): no gold zero — a zero is not a key figure.
        <div className="mt-4">
          <EmptyState
            headline="Nothing needs your approval."
            line="SUNIL parks a task here whenever a plan reaches an action it can't take on its own."
            actionLabel="View decided approvals →"
            actionHref="/approvals?status=all"
          />
        </div>
      ) : (
        <SectionBox
          hero
          open
          heading="Pending approvals"
          fullViewHref="/approvals"
          leading={
            <span
              aria-hidden="true"
              className="font-display text-key font-bold text-accent [text-shadow:0_0_14px_rgba(201,162,39,.32)]"
            >
              {pendingCount}
            </span>
          }
          atRest={
            <>
              Waiting on you
              {nextExpiry ? (
                <>
                  {" · next expiry "}
                  <b
                    className={`font-mono ${
                      nextExpiry.level === "danger" ? "text-danger" : "text-text-secondary"
                    }`}
                  >
                    {nextExpiry.figure}
                  </b>
                </>
              ) : null}
              {oldest ? ` · oldest ${relativeFromNow(oldest.created_at, now).replace(" ago", "")}` : null}
            </>
          }
        >
          <p className="mb-0.5 mt-2 text-micro font-semibold uppercase tracking-micro text-text-muted">
            Top of the queue — summaries are text supplied by the request, shown exactly as received
          </p>
          <div className={stale ? "opacity-85" : undefined}>
            {top3.map((approval) => (
              <div
                key={approval.id}
                className="grid grid-cols-[minmax(0,1fr)] items-center gap-3 border-b border-border py-2.5 last:border-b-0 md:grid-cols-[170px_minmax(0,1fr)_110px]"
              >
                <Link
                  href={`/approvals/${approval.id}`}
                  aria-label={`Pending — ${approval.tool}.${approval.operation} — ${approval.summary} — review and decide`}
                  className="min-w-0 text-text-primary hover:text-accent-hover"
                >
                  <OperationIdentifier tool={approval.tool} operation={approval.operation} />
                </Link>
                {/* The compact quotation pattern — same grammar as the queue's
                    col 3: mono, barred, single line, text node only. */}
                <UntrustedText value={approval.summary} compact />
                <span className="md:text-right">
                  <ExpiryMeter expiresAt={approval.expires_at} now={now} />
                </span>
              </div>
            ))}
          </div>
        </SectionBox>
      )}

      {/* 3 · Secondary grid — every at-rest figure readable without expanding. */}
      <div className="mt-3.5 grid gap-3.5 lg:grid-cols-2">
        {/* Agent activity */}
        {activity.error ? (
          <ErrorPanel
            headline="Couldn't load agent activity."
            detail={describe(activity.error)}
            onRetry={activity.reload}
          />
        ) : (
          <SectionBox
            heading="Agent activity"
            fullViewHref="/activity"
            leading={<LiveDot live={running.length > 0} stale={stale} />}
            atRest={
              <>
                <b className="text-text-secondary">{`${running.length} running`}</b>
                {` · ${parked.length} waiting on you · ${finishedToday} finished today`}
              </>
            }
          >
            {running.map((item) => (
              <SectionRow key={item.id}>
                <StatusPill status="in_progress" context="task" />
                <span className="flex-1 truncate">
                  {item.latest_detail?.project_display_name
                    ? `Checking ${item.latest_detail.project_display_name}… `
                    : ""}
                  <span className="text-text-muted">{`(${item.assigned_agent})`}</span>
                </span>
                <span className="whitespace-nowrap font-mono text-[0.6875rem] text-text-muted">
                  {item.started_at ? elapsedSince(item.started_at, now) : "—"}
                </span>
              </SectionRow>
            ))}
            {parked.map((item) => (
              <SectionRow key={item.id}>
                <StatusPill status="parked" context="task" />
                <span className="flex-1 truncate">
                  Needs approval:{" "}
                  <span className="font-mono text-small">
                    {item.latest_detail?.tool && item.latest_detail?.operation
                      ? `${item.latest_detail.tool}.${item.latest_detail.operation}`
                      : "—"}
                  </span>
                </span>
                <span className="whitespace-nowrap font-mono text-[0.6875rem] text-text-muted">
                  {relativeFromNow(item.created_at, now)}
                </span>
              </SectionRow>
            ))}
            {running.length === 0 && parked.length === 0 ? (
              <p className="py-2 text-small text-text-muted">
                SUNIL is idle. Nothing is running.
              </p>
            ) : null}
          </SectionBox>
        )}

        {/* Tasks */}
        {tasks.error ? (
          <ErrorPanel
            headline="Couldn't load tasks."
            detail={describe(tasks.error)}
            onRetry={tasks.reload}
          />
        ) : (
          <SectionBox
            heading="Tasks"
            fullViewHref="/tasks"
            leading={<Icon name="list-checks" className="text-text-muted" />}
            atRest={
              <>
                <b className="text-text-secondary">
                  {`${(tasks.data?.tasks ?? []).filter((t) => t.status === "in_progress" || t.status === "parked").length} in flight`}
                </b>
                {` · ${(tasks.data?.tasks ?? []).filter((t) => t.status === "failed").length} failed today · ${(tasks.data?.tasks ?? []).filter((t) => t.status === "completed").length} done today`}
              </>
            }
          >
            {(tasks.data?.tasks ?? []).slice(0, 5).map((task) => (
              <SectionRow key={task.id}>
                <StatusPill status={task.status} context="task" />
                {/* `objective` is plan text derived from a user/LLM string —
                    untrusted, same containment (§7.2). */}
                <span className="min-w-0 flex-1">
                  <UntrustedText value={task.objective} compact />
                </span>
                <span className="whitespace-nowrap font-mono text-[0.6875rem] text-text-muted">
                  {shortTime(task.created_at)}
                </span>
              </SectionRow>
            ))}
          </SectionBox>
        )}

        {/* Projects */}
        {projects.error ? (
          <ErrorPanel
            headline="Couldn't load projects."
            detail={describe(projects.error)}
            onRetry={projects.reload}
          />
        ) : (
          <SectionBox
            heading="Projects"
            fullViewHref="/projects"
            leading={<Icon name="folder" className="text-text-muted" />}
            atRest={
              <>
                <b className="text-text-secondary">{`${projects.data?.projects.length ?? 0} tracked`}</b>
                {projects.data?.projects[0]?.last_activity_at
                  ? ` · last activity ${shortTime(projects.data.projects[0].last_activity_at)} (${projects.data.projects[0].display_name})`
                  : null}
              </>
            }
          >
            {(projects.data?.projects ?? []).map((project) => (
              <SectionRow key={project.key}>
                <span className="min-w-0 flex-1 truncate">
                  <b className="text-text-secondary">{project.display_name}</b>{" "}
                  <span className="font-mono text-small text-text-muted">{project.key}</span>
                </span>
                <span className="whitespace-nowrap font-mono text-[0.6875rem] text-text-muted">
                  {project.last_activity_at ? shortTime(project.last_activity_at) : "—"}
                  {project.pending_approvals ? ` · ${project.pending_approvals} pending` : ""}
                </span>
              </SectionRow>
            ))}
          </SectionBox>
        )}

        {/* Recent audit */}
        {audit.error ? (
          <ErrorPanel
            headline="Couldn't load the audit index."
            detail={describe(audit.error)}
            onRetry={audit.reload}
          />
        ) : (
          <SectionBox
            heading="Recent audit"
            fullViewHref="/audit"
            leading={<Icon name="file-search" className="text-text-muted" />}
            atRest={
              <>
                Last turn{" "}
                <b className="text-text-secondary">
                  {audit.data?.turns[0] ? shortTime(audit.data.turns[0].started_at) : "—"}
                </b>
                {` · ${(audit.data?.turns ?? []).filter((t) => t.outcome === "failed").length} failed · ${(audit.data?.turns ?? []).filter((t) => t.outcome === "parked").length} parked today`}
              </>
            }
          >
            {(audit.data?.turns ?? []).slice(0, 4).map((turn) => (
              <SectionRow key={turn.request_id}>
                <Link href={`/audit/${turn.request_id}`} className="font-mono text-small">
                  {turn.request_id}
                </Link>
                {/* C6 carries no conversation label — the id is the only
                    conversation handle the contract returns (fidelity note D-F3). */}
                <span className="min-w-0 flex-1 truncate font-mono text-small text-text-secondary">
                  {turn.conversation_id ?? "—"}
                </span>
                {turn.outcome === "parked" ? (
                  <StatusPill status="parked" context="task" />
                ) : turn.outcome === "failed" ? (
                  <StatusPill
                    status="failed"
                    context="task"
                    label={turn.failure_kind ?? "Failed"}
                  />
                ) : (
                  <StatusPill status="completed" context="task" label="Ok" />
                )}
                <span className="whitespace-nowrap font-mono text-[0.6875rem] text-text-muted">
                  {clockTime(turn.started_at)}
                </span>
              </SectionRow>
            ))}
          </SectionBox>
        )}
      </div>
    </>
  );
}

export function describe(error: unknown): string {
  if (error && typeof error === "object" && "message" in error) {
    const message = String((error as { message: unknown }).message);
    return `${message} Nothing has changed — the data is safe on the server.`;
  }
  return "SUNIL's API didn't respond. Nothing has changed — the data is safe on the server.";
}
