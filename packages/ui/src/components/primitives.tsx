/**
 * Small shared presentational components from PORTAL_SHELL_SPEC.md.
 *
 * None of these fetch anything or hold state; they are the vocabulary the pages are written
 * in. They are safe to render on the server (no hooks, no browser globals).
 */
import type { JSX, ReactNode } from "react";

/* ---------------------------------------------------------------------- */
/* Lamp (§4.1, §8.4, §10.1)                                                */
/* ---------------------------------------------------------------------- */

export type LampState = "on" | "warn" | "error" | "off" | "unknown";

/**
 * `label` is REQUIRED, not optional. DESIGN_TOKENS.md §5.4.6: colour is never the only
 * channel. Making the text mandatory in the type is how that rule is enforced structurally
 * rather than remembered — a lamp cannot be rendered without a text state.
 */
export function Lamp({ state, label }: { state: LampState; label: string }): JSX.Element {
  return (
    <>
      <span className={`sunil-lamp sunil-lamp--${state}`} aria-hidden="true" />
      <span className="sunil-sr-only">{label}</span>
    </>
  );
}

/* ---------------------------------------------------------------------- */
/* Badge / phase chip (§5.4)                                               */
/* ---------------------------------------------------------------------- */

export function Badge({ children }: { children: ReactNode }): JSX.Element {
  return <span className="sunil-badge sunil-type-micro">{children}</span>;
}

/* ---------------------------------------------------------------------- */
/* Spinner (§13 — loading state of buttons and cards)                      */
/* ---------------------------------------------------------------------- */

export function Spinner({ size = "sm" }: { size?: "sm" | "lg" }): JSX.Element {
  return (
    <span
      className={size === "lg" ? "sunil-spinner sunil-spinner--lg" : "sunil-spinner"}
      aria-hidden="true"
    />
  );
}

/* ---------------------------------------------------------------------- */
/* Screen-reader-only text                                                 */
/* ---------------------------------------------------------------------- */

export function SrOnly({ children, id }: { children: ReactNode; id?: string }): JSX.Element {
  return (
    <span className="sunil-sr-only" id={id}>
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------------- */
/* Skeleton (§13). A shape, never text — `--sunil-skeleton-*` is 1.14:1.   */
/* ---------------------------------------------------------------------- */

export function Skeleton({
  width = "100%",
  height = 44,
}: {
  width?: number | string;
  height?: number | string;
}): JSX.Element {
  return <span className="sunil-skeleton" style={{ display: "block", width, height }} />;
}

/* ---------------------------------------------------------------------- */
/* Stat tile — the prototype's `.stat`, reused ONLY for System Health queue */
/* counts (§12 deviation register).                                        */
/* ---------------------------------------------------------------------- */

export function StatTile({
  label,
  value,
  tone = "default",
}: {
  label: string;
  value: string | number;
  tone?: "default" | "danger";
}): JSX.Element {
  return (
    <div className="sunil-stat">
      <span
        className={
          tone === "danger"
            ? "sunil-stat__value sunil-stat__value--danger sunil-type-display-sm"
            : "sunil-stat__value sunil-type-display-sm"
        }
      >
        {value}
      </span>
      <span className="sunil-stat__label sunil-type-micro">{label}</span>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Alert (§7.1). `role="alert"` for errors only — the app-wide assertive    */
/* region is never used for anything routine (§3).                         */
/* ---------------------------------------------------------------------- */

export function Alert({
  tone = "error",
  children,
  id,
}: {
  tone?: "error" | "info";
  children: ReactNode;
  id?: string;
}): JSX.Element {
  return (
    <div
      id={id}
      className={tone === "error" ? "sunil-alert sunil-type-body" : "sunil-alert sunil-alert--info sunil-type-body"}
      role={tone === "error" ? "alert" : undefined}
      tabIndex={tone === "error" ? -1 : undefined}
    >
      <span className="sunil-alert__glyph" aria-hidden="true">
        {tone === "error" ? "⚠" : "ℹ"}
      </span>
      <span>{children}</span>
    </div>
  );
}

/* ---------------------------------------------------------------------- */
/* Empty state (§13). Say what is not there and why, in one sentence, in    */
/* the product's voice. Never "Nothing here yet!".                         */
/* ---------------------------------------------------------------------- */

export function EmptyState({
  glyph = "○",
  children,
  action,
}: {
  glyph?: string;
  children: ReactNode;
  action?: ReactNode;
}): JSX.Element {
  return (
    <div className="sunil-panel__empty">
      <span aria-hidden="true" className="sunil-type-display-sm">
        {glyph}
      </span>
      <p className="sunil-type-body">{children}</p>
      {action}
    </div>
  );
}
