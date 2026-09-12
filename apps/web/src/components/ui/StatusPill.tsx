import { Icon, type IconName } from "./Icon";
import type { ApprovalStatus, TaskStatus } from "@/lib/types";

/**
 * Status as **icon + uppercase text + colour**, never colour alone (§12.3).
 * The table below IS spec §12.3 — including the row-edge pattern, so a
 * greyscale print or a fully colour-blind owner can still classify every row.
 */

export type PillStatus = ApprovalStatus | TaskStatus;

interface PillSpec {
  icon: IconName;
  text: string;
  colour: string;
  /** Tailwind classes for the 2px row edge (solid / dashed / dotted). */
  edge: string;
}

const SPEC: Record<PillStatus, PillSpec> = {
  pending: {
    icon: "clock",
    text: "Pending",
    colour: "text-status-pending",
    edge: "border-l-2 border-solid border-l-status-pending",
  },
  approved: {
    icon: "check",
    text: "Approved",
    colour: "text-status-approved",
    edge: "border-l-2 border-solid border-l-status-approved",
  },
  consumed: {
    icon: "check-check",
    text: "Consumed",
    colour: "text-status-consumed",
    edge: "border-l-2 border-solid border-l-status-consumed",
  },
  refused: {
    icon: "x",
    text: "Refused",
    colour: "text-status-refused",
    edge: "border-l-2 border-dashed border-l-status-refused",
  },
  expired: {
    icon: "ban",
    text: "Expired",
    colour: "text-status-expired",
    edge: "border-l-2 border-dotted border-l-status-expired",
  },
  in_progress: {
    icon: "loader",
    text: "Running",
    colour: "text-accent",
    edge: "border-l-2 border-solid border-l-accent",
  },
  parked: {
    icon: "pause",
    text: "Parked",
    colour: "text-warning",
    edge: "border-l-2 border-solid border-l-warning",
  },
  failed: {
    icon: "alert-triangle",
    text: "Failed",
    colour: "text-danger",
    edge: "border-l-2 border-dashed border-l-danger",
  },
  completed: {
    icon: "check",
    text: "Done",
    colour: "text-success",
    edge: "border-l-2 border-solid border-l-success",
  },
  // `tasks.status = pending` (queued, not yet started) — not an approval state.
  // Rendered neutrally: nothing has happened yet and nothing is wrong.
};

const QUEUED: PillSpec = {
  icon: "clock",
  text: "Queued",
  colour: "text-text-muted",
  edge: "border-l-2 border-dotted border-l-text-muted",
};

export function pillSpec(status: PillStatus, context: "approval" | "task" = "approval"): PillSpec {
  if (status === "pending" && context === "task") return QUEUED;
  return SPEC[status] ?? QUEUED;
}

export function rowEdgeClass(status: PillStatus, context: "approval" | "task" = "approval") {
  return pillSpec(status, context).edge;
}

export interface StatusPillProps {
  status: PillStatus;
  context?: "approval" | "task";
  /** Override the label (e.g. an audit outcome pill reading `tool_failed`). */
  label?: string;
  size?: "sm" | "md";
}

export function StatusPill({ status, context = "approval", label, size = "sm" }: StatusPillProps) {
  const spec = pillSpec(status, context);
  return (
    <span
      className={`inline-flex items-center gap-[5px] whitespace-nowrap rounded-full border border-current ${
        size === "md" ? "px-2.5 py-[3px]" : "px-[9px] py-[3px]"
      } text-micro font-semibold uppercase tracking-pill ${spec.colour}`}
    >
      <Icon name={spec.icon} size={12} />
      {label ?? spec.text}
    </span>
  );
}
