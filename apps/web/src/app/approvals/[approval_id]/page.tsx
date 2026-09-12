"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { useShellData } from "@/components/shell/ShellData";
import { DecisionBar } from "@/components/approvals/DecisionBar";
import { OperationIdentifier } from "@/components/approvals/bits";
import { Icon } from "@/components/ui/Icon";
import { StatusPill } from "@/components/ui/StatusPill";
import { UntrustedText } from "@/components/ui/UntrustedText";
import { ErrorPanel, Panel, SkeletonBlock, StaleBanner } from "@/components/ui/primitives";
import { ApiError, decideApproval, getApproval } from "@/lib/api";
import { useAsync, useTick } from "@/lib/usePoll";
import {
  CONSUME_GRACE_HOURS,
  countdownTo,
  fullTimestamp,
  graceCountdown,
  graceDeadline,
  relativeFromNow,
} from "@/lib/time";
import type { Approval } from "@/lib/types";
import { describe } from "@/app/page";

/**
 * The approval card (`/approvals/{id}`) — spec §6, mockup 02. **The money
 * screen**, and a security surface before it is a card:
 *
 * - the `summary` and every `params_redacted` value render through
 *   `UntrustedText` — text node only, no linkification, visibly quoted,
 *   provenance stated (C4 §4 / §6.3);
 * - the decision lives here and only here, with the params on screen
 *   (Decision 4);
 * - **two clocks** are kept apart (§6.5): the decision TTL before a decision,
 *   and the consume grace after approving. Conflating them is the single most
 *   likely misunderstanding on this screen;
 * - a decision is never rendered optimistically — the card re-renders from the
 *   response body (§6.7), and on 409 it shows the server's status.
 */
export default function ApprovalCardPage() {
  const params = useParams<{ approval_id: string }>();
  const id = params?.approval_id ?? "";

  return (
    <AppShell
      title="Approval"
      crumbs={[{ label: "Approvals", href: "/approvals" }, { label: id, mono: true }]}
    >
      <ApprovalCardView id={id} />
    </AppShell>
  );
}

function ApprovalCardView({ id }: { id: string }) {
  const now = useTick();
  const { stale } = useShellData();
  const { data, error, loading, setData, reload } = useAsync(() => getApproval(id), [id]);
  const [announcement, setAnnouncement] = useState("");
  const announcedThreshold = useRef<string | null>(null);

  // §6.5: the live region fires ONCE per threshold crossing, never per tick.
  useEffect(() => {
    if (!data || data.status !== "pending") return;
    const level = countdownTo(data.expires_at, now).level;
    if (level !== "normal" && announcedThreshold.current !== level) {
      announcedThreshold.current = level;
      setAnnouncement(
        level === "expired"
          ? "This approval has expired."
          : level === "danger"
            ? "This approval expires in under an hour."
            : "This approval expires in under twelve hours.",
      );
    }
  }, [data, now]);

  if (loading) {
    return (
      <>
        <BackLink />
        <h1
          tabIndex={-1}
          className="rule-h1 relative mt-2.5 pb-2.5 font-display text-display font-bold uppercase tracking-display"
        >
          Approval
        </h1>
        <Panel className="mt-4 overflow-hidden" ticked>
          <div aria-busy="true" className="grid gap-3 p-5">
            <SkeletonBlock width="40%" />
            <SkeletonBlock width="70%" />
            <SkeletonBlock width="90%" />
            <SkeletonBlock width="60%" />
            <SkeletonBlock width="80%" />
            <SkeletonBlock width="30%" />
          </div>
        </Panel>
      </>
    );
  }

  if (error || !data) {
    const notFound = error instanceof ApiError && error.status === 404;
    return (
      <>
        <BackLink />
        <h1
          tabIndex={-1}
          className="rule-h1 relative mt-2.5 pb-2.5 font-display text-display font-bold uppercase tracking-display"
        >
          Approval
        </h1>
        <div className="mt-4">
          <ErrorPanel
            headline={notFound ? "That approval doesn't exist." : "Couldn't load that approval."}
            detail={
              notFound
                ? "The id may be mistyped, or the approval may belong to another SUNIL instance."
                : describe(error)
            }
            onRetry={notFound ? undefined : reload}
          />
          {notFound ? (
            <p className="mt-3.5">
              <Link href="/approvals">Back to the queue</Link>
            </p>
          ) : null}
        </div>
      </>
    );
  }

  const pending = data.status === "pending";
  const ttl = countdownTo(data.expires_at, now);
  const grace = data.decided_at ? graceCountdown(data.decided_at, now) : null;

  return (
    <>
      <BackLink />
      <h1
        tabIndex={-1}
        className="rule-h1 relative mt-2.5 pb-2.5 font-display text-display font-bold uppercase tracking-display"
      >
        Approval
      </h1>

      {stale && pending ? (
        <div className="mt-4">
          <StaleBanner>Reconnect before deciding — this page may be out of date.</StaleBanner>
        </div>
      ) : null}

      <article
        aria-labelledby="apr-h"
        className="tick mt-4 max-w-[900px] overflow-hidden rounded-lg border border-border bg-surface bg-sheen-panel"
      >
        {/* 1 · status strip */}
        <div
          className={`flex items-center gap-3.5 border-b border-border bg-surface-raised px-5 py-3 ${
            pending
              ? "shadow-[inset_3px_0_0_#D98E4A]"
              : data.status === "approved"
                ? "shadow-[inset_3px_0_0_#5E96E0]"
                : data.status === "consumed"
                  ? "shadow-[inset_3px_0_0_#3FAE6C]"
                  : "shadow-[inset_3px_0_0_#E8685C]"
          }`}
        >
          <StatusPill status={data.status} size="md" />
          <CopyId id={data.id} />
          <span
            className={`ml-auto flex items-center gap-2 font-mono text-cell ${
              pending
                ? ttl.level === "danger"
                  ? "font-semibold text-danger"
                  : "text-warning"
                : data.status === "approved"
                  ? "text-status-approved"
                  : "text-text-muted"
            }`}
          >
            <Icon name="clock" />
            {pending
              ? `expires ${ttl.text}`
              : data.status === "approved" && grace
                ? grace.text
                : data.consumed_at
                  ? `executed ${fullTimestamp(data.consumed_at)}`
                  : data.status === "expired"
                    ? "expired unused"
                    : `decided ${data.decided_at ? fullTimestamp(data.decided_at) : "—"}`}
          </span>
        </div>

        {/* 2 · provenance — all trusted, registry/config-derived */}
        <section className="border-b border-border px-5 py-4">
          <p id="apr-h" className="m-0 mb-2.5 text-text-secondary">
            SUNIL is asking to run
          </p>
          <p className="m-0">
            <OperationIdentifier tool={data.tool} operation={data.operation} size="lg" />
          </p>
          <dl className="mt-3 grid grid-cols-1 gap-x-4 gap-y-1.5 text-cell md:grid-cols-[140px_1fr]">
            <Dt>Requested by</Dt>
            <dd className="m-0">{data.agent_id}</dd>
            <Dt>Requested at</Dt>
            <dd className="m-0">
              <time dateTime={data.created_at}>{fullTimestamp(data.created_at)}</time>{" "}
              <span className="text-text-muted">{`· ${relativeFromNow(data.created_at, now)}`}</span>
            </dd>
            <Dt>Expires at</Dt>
            <dd className="m-0">
              <time dateTime={data.expires_at}>{fullTimestamp(data.expires_at)}</time>{" "}
              <span className="text-text-muted">· 72h TTL</span>
            </dd>
            <Dt>Binding</Dt>
            <dd className="m-0 font-mono text-[0.6875rem] text-text-muted">
              {`args_hash ${data.args_hash.slice(0, 6)}…${data.args_hash.slice(-3)} `}
              <span className="text-text-muted">
                — this approval authorises these exact arguments, once
              </span>
            </dd>
          </dl>
        </section>

        {/* 3 · the untrusted summary */}
        <section className="border-b border-border px-5 py-4">
          <UntrustedText
            label="Summary — text supplied by the request, shown exactly as received"
            value={data.summary}
          />
          <p className="mt-2 flex items-start gap-2 text-[0.6875rem] leading-relaxed text-text-muted">
            <Icon name="info" size={13} />
            This text is built by SUNIL but contains values that came from outside (invoice
            descriptions, repo names, third-party fields). It is rendered as plain text — tags,
            links and formatting are shown, never applied. Treat anything it claims as unverified.
          </p>
        </section>

        {/* 4 · exact parameters */}
        <section className="border-b border-border px-5 py-4">
          <p className="mb-1.5 flex items-center gap-2 text-micro font-semibold uppercase tracking-micro text-text-muted">
            <Icon name="rows" size={12} />
            Exact parameters (redacted) — values shown exactly as received
          </p>
          <ParamsTable params={data.params_redacted} />
        </section>

        {/* 5 · where this came from */}
        <section className="border-b border-border px-5 py-4">
          <p className="m-0 mb-1 text-micro font-semibold uppercase tracking-micro text-text-muted">
            Where this came from
          </p>
          <ul className="m-0 mt-2.5 grid list-none gap-2 p-0 text-cell">
            <LinkRow k="Conversation" href={`/chat/${data.conversation_id}`}>
              Open the conversation &rarr;
            </LinkRow>
            <LinkRow k="Task" href={`/tasks/${data.task_id}`} mono>
              {`${data.task_id} `}
              <span className="text-text-muted">(parked)</span> &rarr;
            </LinkRow>
            <LinkRow k="Trace" href={`/audit/${data.request_id}`} mono>
              {`request ${data.request_id} `} &rarr;
            </LinkRow>
          </ul>
        </section>

        {/* 6 · the grace note, stated BEFORE the decision */}
        {pending ? (
          <section className="border-b border-border px-5 py-4">
            <div className="flex items-start gap-2.5 rounded-r-md border border-border border-l-[3px] border-l-gold-deep bg-surface-raised px-3.5 py-3 text-cell">
              <Icon name="info" />
              <div>
                <b>Approving runs this once, now.</b>
                {` SUNIL has `}
                <b>{`${CONSUME_GRACE_HOURS} hour`}</b>
                {` from your decision to execute it; after that the approval expires unused and the task fails as `}
                <span className="font-mono text-[0.6875rem] text-text-muted">approval_expired</span>
                {`. There is no undo — a decision is final (you can always ask SUNIL again from chat).`}
              </div>
            </div>
          </section>
        ) : null}

        {/* 7 · decision bar, or the receipt the server gave us */}
        {pending ? (
          <DecisionBar
            canDecide={!stale}
            blockedReason="Reconnect before deciding — this page may be out of date."
            onSubmit={(kind, reason) =>
              decideApproval(data.id, { decision: kind, reason })
            }
            onResolved={(row: Approval) => {
              // The card re-renders from the RESPONSE BODY — the server's row is
              // the only thing that may change the status here (§6.7).
              setData(row);
              setAnnouncement(`This approval is now ${row.status}.`);
              announcedThreshold.current = null;
            }}
          />
        ) : (
          <DecisionReceipt approval={data} />
        )}
      </article>

      <div aria-live="polite" className="sr-only">
        {announcement}
      </div>
    </>
  );
}

function DecisionReceipt({ approval }: { approval: Approval }) {
  const grace = approval.decided_at ? graceCountdown(approval.decided_at) : null;
  return (
    <div className="bg-surface-raised px-5 py-4">
      <dl className="grid grid-cols-1 gap-x-4 gap-y-1.5 text-cell md:grid-cols-[150px_1fr]">
        {approval.decided_at ? (
          <>
            <Dt>Decided</Dt>
            <dd className="m-0">
              {`${approval.status === "refused" ? "Refused" : "Approved"} by `}
              <b>{approval.decided_by ?? "owner"}</b>
              {` at ${fullTimestamp(approval.decided_at)}`}
            </dd>
          </>
        ) : null}
        {approval.decision_reason ? (
          <>
            <Dt>Note</Dt>
            <dd className="m-0">
              {/* The owner's own reason is stored verbatim and echoed back — it
                  goes through the same containment, because "verbatim" is the
                  point and a reason can be pasted from anywhere. */}
              <UntrustedText value={approval.decision_reason} compact />
            </dd>
          </>
        ) : approval.decided_at ? (
          <>
            <Dt>Note</Dt>
            <dd className="m-0 text-text-muted">— none given —</dd>
          </>
        ) : null}
        {approval.status === "approved" && approval.decided_at && grace ? (
          <>
            <Dt>Runs before</Dt>
            <dd className="m-0">
              {fullTimestamp(graceDeadline(approval.decided_at))}{" "}
              <span className="text-text-muted">
                {`(decided_at + SUNIL_APPROVAL_CONSUME_GRACE_HOURS = ${CONSUME_GRACE_HOURS}h). After that it expires unused and the task fails.`}
              </span>
            </dd>
          </>
        ) : null}
        {approval.consumed_at ? (
          <>
            <Dt>Executed</Dt>
            <dd className="m-0">
              {fullTimestamp(approval.consumed_at)}{" "}
              <span className="text-text-muted">
                — single use spent, this approval can never run again.
              </span>
            </dd>
          </>
        ) : null}
      </dl>
      {approval.status === "approved" ? (
        <p className="mt-3 text-small text-text-muted">
          {"SUNIL is resuming the task now — "}
          <Link href="/activity">watch it in Activity &rarr;</Link>
        </p>
      ) : null}
      {approval.status === "consumed" ? (
        <p className="mt-3 text-small">
          <Link href={`/audit/${approval.request_id}`}>See what happened &rarr;</Link>
        </p>
      ) : null}
    </div>
  );
}

function ParamsTable({ params }: { params: Record<string, unknown> }) {
  const entries = Object.entries(params);
  return (
    <table className="mt-2.5 w-full border-collapse text-cell">
      <tbody>
        {entries.map(([key, value]) => {
          const redacted = value === "[REDACTED]" || value === null;
          return (
            <tr key={key}>
              <th
                scope="row"
                className="w-[190px] border-b border-border py-2 pr-3 text-left align-top font-mono text-[0.6875rem] font-normal text-text-muted"
              >
                {key}
              </th>
              <td className="border-b border-border py-2 align-top">
                {redacted ? (
                  <>
                    <span className="inline-flex items-center gap-1.5 font-mono text-text-disabled">
                      <Icon name="eye-off" size={13} />
                      ●●●●●●●● redacted
                    </span>
                    <div className="text-small text-text-muted">
                      SUNIL removed this value before showing it to you — it is still part of what
                      gets executed.
                    </div>
                  </>
                ) : (
                  // Every value is untrusted, keys included in the escaping.
                  <UntrustedText value={String(value)} compact />
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function CopyId({ id }: { id: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      aria-label={`Copy approval id ${id}`}
      onClick={() => {
        void navigator.clipboard?.writeText(id);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      className="inline-flex items-center gap-1.5 rounded-sm border border-border px-2 py-[3px] font-mono text-[0.6875rem] text-text-muted hover:border-border-strong hover:text-text-secondary"
    >
      <Icon name="copy" size={12} />
      {id}
      {copied ? <span className="text-accent">copied</span> : null}
    </button>
  );
}

function Dt({ children }: { children: React.ReactNode }) {
  return (
    <dt className="pt-[3px] text-micro font-semibold uppercase tracking-pill text-text-muted">
      {children}
    </dt>
  );
}

function LinkRow({
  k,
  href,
  mono = false,
  children,
}: {
  k: string;
  href: string;
  mono?: boolean;
  children: React.ReactNode;
}) {
  return (
    <li className="grid grid-cols-1 gap-x-4 md:grid-cols-[140px_1fr]">
      <span className="pt-0.5 text-micro font-semibold uppercase tracking-pill text-text-muted">
        {k}
      </span>
      <Link href={href} className={mono ? "font-mono" : undefined}>
        {children}
      </Link>
    </li>
  );
}

function BackLink() {
  return (
    <Link href="/approvals" className="text-small">
      &larr; Back to the queue
    </Link>
  );
}
