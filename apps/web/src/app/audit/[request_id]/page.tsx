"use client";

import { useParams } from "next/navigation";
import { AppShell } from "@/components/shell/AppShell";
import { Icon } from "@/components/ui/Icon";
import { UntrustedText } from "@/components/ui/UntrustedText";
import {
  Button,
  ComingWithApi,
  EmptyState,
  ErrorPanel,
  Panel,
  SectionHeading,
  SkeletonRows,
  ViewHeading,
  ViewSubhead,
} from "@/components/ui/primitives";
import { getAuditTrace } from "@/lib/api";
import { useAsync } from "@/lib/usePoll";
import { clockTime } from "@/lib/time";
import type { AuditEvent, StageName } from "@/lib/types";
import { describe } from "@/app/page";

/**
 * The trace (`/audit/{request_id}`) — spec §10.2, mockup 05.
 *
 * Rows are native `<details>`: keyboard operable for free, `aria-expanded`
 * handled by the browser, no ARIA to get wrong. Exception rows (a non-`allow`
 * permission decision, `ok: false`, a non-`ok` outcome) arrive **expanded**
 * and take a warning/danger edge — an owner opening a trace wants the
 * exception, not row 1.
 *
 * `detail` values are rendered under the §6.3 plain-text rules, with no
 * exception for a "developer-facing" screen: `audit_events.detail` may carry a
 * truncated excerpt of untrusted content (T-32).
 */

const STAGE_LABELS: Record<StageName, string> = {
  message_received: "Received your message",
  context_loaded: "Loaded conversation context",
  memory_retrieved: "Checked memory",
  model_selected: "Chose a model",
  llm_io: "Interpreted the request",
  plan_created: "Created a plan",
  agent_started: "Started the agent",
  tool_requested: "Asked to use a tool",
  permission_decision: "Permission check",
  tool_result: "Tool result",
  agent_result: "Analysed the result",
  final_response: "Prepared the answer",
};

function isException(event: AuditEvent): "danger" | "warning" | null {
  const detail = event.detail ?? {};
  if (event.stage === "permission_decision" && detail.decision !== "allow") return "warning";
  if (event.stage === "tool_result" && detail.ok === false) return "danger";
  if (event.stage === "final_response" && detail.outcome !== "ok") return "warning";
  return null;
}

export default function AuditTracePage() {
  const params = useParams<{ request_id: string }>();
  const id = params?.request_id ?? "";
  return (
    <AppShell title="Trace" crumbs={[{ label: "Audit", href: "/audit" }, { label: id, mono: true }]}>
      <TraceView id={id} />
    </AppShell>
  );
}

function TraceView({ id }: { id: string }) {
  const { data, error, loading, reload } = useAsync(() => getAuditTrace(id), [id]);
  const events = data?.events ?? [];
  const approvalEvents = data?.approval_events ?? [];
  const base = events[0] ? Date.parse(events[0].at) : 0;

  if (loading) return <SkeletonRows rows={12} columns={["60px", "1fr", "80px"]} />;

  if (error) {
    return (
      <>
        <ViewHeading>Trace</ViewHeading>
        <div className="mt-4">
          <EmptyState
            headline="No trace for that request id."
            line="Ids look like 01JQ8Z…. Check the id, or browse recent turns."
            actionLabel="Browse recent"
            actionHref="/audit"
            icon="file-search"
          />
          <div className="mt-3.5">
            <ErrorPanel headline="Couldn't load that trace." detail={describe(error)} onRetry={reload} />
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <ViewHeading>Trace</ViewHeading>
      <ViewSubhead>
        <span className="font-mono text-data text-text-primary">{id}</span>
        {` · ${events.length} of 12 stages`}
      </ViewSubhead>

      <div className="mt-4 grid gap-4">
        {events.length !== 12 ? (
          <div
            role="status"
            className="flex items-start gap-2.5 rounded-md border border-warning bg-surface-raised px-3.5 py-3 text-cell text-warning"
          >
            <Icon name="alert-triangle" />
            <span>{`This trace has ${events.length} of 12 stages — the turn ended early.`}</span>
          </div>
        ) : null}

        <div className="flex gap-3">
          <Button onClick={() => void navigator.clipboard?.writeText(id)}>Copy request_id</Button>
          <Button
            onClick={() =>
              void navigator.clipboard?.writeText(
                events
                  .map(
                    (e) =>
                      `${e.seq}. ${STAGE_LABELS[e.stage as StageName] ?? e.stage} (+${offset(e, base)}) — ${e.summary}`,
                  )
                  .join("\n"),
              )
            }
          >
            Copy trace as text
          </Button>
        </div>

        <Panel className="tick overflow-hidden">
          {events.map((event) => (
            <StageRow key={event.seq} event={event} base={base} />
          ))}
        </Panel>

        {approvalEvents.length > 0 ? (
          <section className="grid gap-2.5">
            <SectionHeading>After your decision — continuation</SectionHeading>
            <div
              className="flex items-center gap-2.5 rounded-md border border-border bg-surface-raised px-3.5 py-2.5 text-cell text-warning"
              role="note"
            >
              <Icon name="pause" />
              {/* Without this marker the offset column jumps from +3.1s to
                  +1583s and reads as a performance disaster rather than a
                  human lunch break (§10.2, Decision 8). */}
              waiting for you — the gap below is human time, not compute
            </div>
            <Panel className="overflow-hidden">
              {approvalEvents.map((event) => (
                <StageRow key={event.seq} event={event} base={base} />
              ))}
            </Panel>
          </section>
        ) : null}

        <ComingWithApi endpoint="GET /api/v1/audit/{request_id} (spec §13.3)" />
      </div>
    </>
  );
}

function offset(event: AuditEvent, base: number): string {
  const ms = Date.parse(event.at) - base;
  return `${(ms / 1000).toFixed(1)}s`;
}

function StageRow({ event, base }: { event: AuditEvent; base: number }) {
  const exception = isException(event);
  const label = STAGE_LABELS[event.stage as StageName] ?? event.stage;
  const keys = Object.entries(event.detail ?? {});

  return (
    <details
      open={exception !== null}
      className={`group border-b border-border last:border-b-0 ${
        exception === "danger"
          ? "border-l-2 border-l-danger"
          : exception === "warning"
            ? "border-l-2 border-l-warning"
            : ""
      }`}
    >
      <summary className="flex cursor-pointer items-center gap-3 px-3.5 py-2.5 hover:bg-surface-raised">
        <span className="w-6 font-mono text-data text-text-muted">{event.seq}</span>
        <span className="min-w-0 flex-1">
          <b className="text-text-secondary">{label}</b>
          <span className="block truncate text-small text-text-muted">{event.summary}</span>
        </span>
        <span className="font-mono text-data text-text-muted">{`+${offset(event, base)}`}</span>
        <Icon
          name="chevron-right"
          className="text-text-muted transition-transform duration-200 ease-standard group-open:rotate-90"
        />
      </summary>
      <div className="bg-surface-raised px-3.5 py-3">
        {keys.length > 0 ? (
          <dl className="grid grid-cols-[180px_1fr] gap-x-4 gap-y-1 text-cell">
            {keys.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-mono text-[0.6875rem] text-text-muted">{key}</dt>
                <dd className="m-0 min-w-0">
                  {/* Contracted detail keys may still carry outside content. */}
                  <UntrustedText value={typeof value === "string" ? value : JSON.stringify(value)} compact />
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="m-0 text-small text-text-muted">No contracted detail keys on this stage.</p>
        )}
        <p className="mb-1 mt-3 text-micro font-semibold uppercase tracking-micro text-text-muted">
          Raw detail — shown exactly as recorded
        </p>
        <UntrustedText value={JSON.stringify(event.detail ?? {}, null, 2)} />
        <p className="mt-2 text-small text-text-muted">{`Recorded at ${clockTime(event.at)} by ${event.actor}`}</p>
      </div>
    </details>
  );
}
