import Link from "next/link";
import type { ReactNode } from "react";
import { Icon } from "./Icon";

/**
 * The shared view furniture: heading, panel, the four required states
 * (loading / empty / error / populated) and the §1.5 stale banner.
 *
 * Spec §2.1 is a rule, not a suggestion: "a view that ships without all five
 * is incomplete, not mostly done". Having them as components is how that rule
 * stays cheap to obey.
 */

export function ViewHeading({ children }: { children: ReactNode }) {
  return (
    <h1
      tabIndex={-1}
      className="rule-h1 relative m-0 pb-2.5 font-display text-display font-bold uppercase tracking-display text-text-primary"
    >
      {children}
    </h1>
  );
}

export function ViewSubhead({ children }: { children: ReactNode }) {
  return <p className="mb-0 mt-2 text-small text-text-muted">{children}</p>;
}

export function SectionHeading({ children, as = "h2" }: { children: ReactNode; as?: "h2" | "h3" }) {
  const Tag = as;
  return (
    <Tag className="m-0 font-display text-h2 font-bold uppercase tracking-h2 text-text-secondary">
      {children}
    </Tag>
  );
}

export function Panel({
  children,
  className = "",
  ticked = false,
}: {
  children: ReactNode;
  className?: string;
  ticked?: boolean;
}) {
  return (
    <div
      className={`rounded-md border border-border bg-surface bg-sheen-panel ${
        ticked ? "tick" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function Button({
  children,
  onClick,
  variant = "ghost",
  type = "button",
  disabled = false,
  className = "",
  ...rest
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "ghost" | "primary" | "danger";
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
} & Record<string, unknown>) {
  const base =
    "inline-flex min-h-[40px] items-center justify-center gap-2 rounded-md border px-4 py-2.5 font-body text-cell font-semibold disabled:cursor-not-allowed disabled:opacity-45";
  const variants = {
    ghost: "border-border-strong bg-transparent text-accent hover:border-accent hover:bg-surface-raised",
    primary:
      "border-accent bg-accent bg-sheen-metal text-accent-on hover:bg-accent-hover active:bg-accent-active",
    danger: "border-danger bg-transparent text-danger hover:bg-danger/10",
  } as const;

  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`${base} ${variants[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

export function SkeletonBlock({ width = "100%" }: { width?: string }) {
  return <div className="h-[13px] rounded-sm bg-surface-raised" style={{ width }} />;
}

/** §2.1 — 5 rows at the real row height, so nothing shifts when data lands. */
export function SkeletonRows({
  rows = 5,
  columns = ["90px", "190px", "1fr", "110px", "90px"],
}: {
  rows?: number;
  columns?: string[];
}) {
  return (
    <Panel className="overflow-hidden" >
      <div aria-busy="true" aria-live="off">
        {Array.from({ length: rows }).map((_, r) => (
          <div
            key={r}
            className="grid gap-3.5 border-b border-border px-3.5 py-3 last:border-b-0"
            style={{ gridTemplateColumns: columns.join(" ") }}
          >
            {columns.map((_c, i) => (
              <SkeletonBlock key={i} width={i === columns.length - 2 ? "80%" : "100%"} />
            ))}
          </div>
        ))}
      </div>
      <span className="sr-only">Loading…</span>
    </Panel>
  );
}

/** §2.1 — headline, one explanatory line, one action. Never "No data". */
export function EmptyState({
  headline,
  line,
  actionLabel,
  actionHref,
  onAction,
  icon = "shield-check",
}: {
  headline: string;
  line: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
  icon?: Parameters<typeof Icon>[0]["name"];
}) {
  return (
    <Panel className="px-4 py-8 text-center">
      <Icon name={icon} size={22} className="mx-auto mb-3 text-success" />
      <p className="m-0 mb-2 font-display text-h2 font-bold uppercase tracking-h2 text-text-secondary">
        {headline}
      </p>
      <p className="mx-auto mb-4 max-w-[52ch] text-small text-text-muted">{line}</p>
      {actionHref ? (
        <Link
          href={actionHref}
          className="inline-flex min-h-[40px] items-center gap-2 rounded-md border border-border-strong px-4 py-2.5 text-cell font-semibold text-accent hover:border-accent hover:bg-surface-raised hover:no-underline"
        >
          {actionLabel}
        </Link>
      ) : actionLabel ? (
        <Button onClick={onAction}>{actionLabel}</Button>
      ) : null}
    </Panel>
  );
}

/** §2.1 — what failed, what the owner can do, and a real retry. */
export function ErrorPanel({
  headline,
  detail,
  onRetry,
}: {
  headline: string;
  detail: string;
  onRetry?: () => void;
}) {
  return (
    <Panel className="p-4">
      <div className="flex items-start gap-2.5 rounded-md border border-danger bg-surface-raised px-3.5 py-3 text-cell text-danger">
        <Icon name="alert-triangle" />
        <div>
          <b>{headline}</b>
          <br />
          <span className="text-small">{detail}</span>
        </div>
      </div>
      {onRetry ? (
        <div className="mt-3.5">
          <Button onClick={onRetry}>Try again</Button>
        </div>
      ) : null}
    </Panel>
  );
}

/** §1.5 — the data stays, the banner tells the truth. */
export function StaleBanner({ lastGoodAt, children }: { lastGoodAt?: string; children?: ReactNode }) {
  return (
    <div
      role="status"
      className="mb-3.5 flex items-start gap-2.5 rounded-md border border-warning bg-surface-raised px-3.5 py-3 text-cell text-warning"
    >
      <Icon name="clock" />
      <div>
        <b>
          {lastGoodAt
            ? `Can't reach SUNIL — showing data from ${lastGoodAt}.`
            : "Can't reach SUNIL — showing the last data it sent."}
        </b>
        {children ? (
          <>
            <br />
            <span className="text-small">{children}</span>
          </>
        ) : null}
      </div>
    </div>
  );
}

/** §A.6 rule 1 — the summary rail: 3–5 figures at rest, one may be gold. */
export function StatRail({
  stats,
  label = "Summary",
}: {
  label?: string;
  stats: { figure: string; caption: string; tone?: "default" | "key" | "danger" | "warning" }[];
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="mt-4 grid gap-px overflow-hidden rounded-md border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]"
    >
      {stats.map((stat) => (
        <div key={stat.caption} className="bg-surface px-3.5 py-2.5">
          <b
            className={`block font-display text-stat font-bold leading-[1.2] tracking-stat ${
              stat.tone === "key"
                ? "text-accent [text-shadow:0_0_14px_rgba(201,162,39,.32)]"
                : stat.tone === "danger"
                  ? "text-danger"
                  : stat.tone === "warning"
                    ? "text-warning"
                    : "text-text-secondary"
            }`}
          >
            {stat.figure}
          </b>
          <span className="text-micro font-semibold uppercase tracking-micro text-text-muted">
            {stat.caption}
          </span>
        </div>
      ))}
    </div>
  );
}

/** §A.6 rule 2 — relative AND absolute, at rest, never hover-only. */
export function Timestamp({ iso, relative, absolute }: { iso: string; relative: string; absolute: string }) {
  return (
    <span className="block">
      <time dateTime={iso} className="block">
        {relative}
      </time>
      <span className="block font-mono text-[0.6875rem] text-text-muted">{absolute}</span>
    </span>
  );
}

/** A stub section for a view whose C6 endpoint is not frozen yet (Q1). */
export function ComingWithApi({ endpoint }: { endpoint: string }) {
  return (
    <Panel className="p-4">
      <div className="flex items-start gap-2.5 text-cell text-text-muted">
        <Icon name="info" className="text-warning" />
        <div>
          <b className="text-text-secondary">
            This view renders against the mock ops-read API.
          </b>
          <br />
          <span className="text-small">
            {`Its shape is `}
            <span className="font-mono text-[0.6875rem] text-text-primary">{endpoint}</span>
            {` — the spec §13 proposal the Architect is freezing as C6. Layout, states and
            containment rules are final; the data source flips at integration.`}
          </span>
        </div>
      </div>
    </Panel>
  );
}
