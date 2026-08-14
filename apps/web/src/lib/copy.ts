import type { TraceStep } from "@/components/chat";
import type { StageName } from "./phases";

/**
 * "The API sends enums and data. The web app owns every human-readable
 * string" (§6/§11.2). This file is that one place — everything here reads
 * a stage/enum/config value and returns Designer-approved or Designer-
 * adjacent copy. `ErrorCard` and `WorkIndicator` (T15) already embed their
 * own fixed per-variant/per-phase copy the same way; this file covers copy
 * that depends on *data* (a project list, a trace stage, a timestamp) or is
 * conditional on an architecture decision (the cancellation note, ADR-010).
 */

/** "10:41 am" — the format `M1_CHAT_SPEC.md`'s own examples use throughout. */
export function formatTimestamp(input: string | Date): string {
  const date = typeof input === "string" ? new Date(input) : input;
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }).toLowerCase();
}

export interface KnownProject {
  key: string;
  display_name: string;
}

/**
 * STOPGAP — flagged to the Delivery Manager. §6's frozen contract has no
 * endpoint to fetch the configured-project list *before* the first turn:
 * `known_projects` only appears inside an `unknown_project` failure
 * response, which by definition can't exist before any message has been
 * sent. The empty-state chips (M1_CHAT_SPEC.md §3) need that list anyway.
 * This mirrors the single M1 entry in `config/projects.yaml`
 * (`easy_clean_workforce` → "EasyClean Workforce") rather than inventing a
 * name, but it is still a hard-coded stand-in for a real API call and
 * should be replaced the moment the Architect names one (a new endpoint,
 * or a field added to `GET /api/v1/auth/session`).
 */
export const FALLBACK_KNOWN_PROJECTS: KnownProject[] = [
  { key: "easy_clean_workforce", display_name: "EasyClean Workforce" },
];

export function formatKnownProjectList(projects: KnownProject[]): string {
  return projects.map((project) => project.display_name).join(", ");
}

/** Empty-state suggestion chips (§3) — shares its project source with `unknown_project`'s copy (§5.9/§11.3) so they can never drift. */
export function suggestionsFor(projects: KnownProject[]): string[] {
  return projects.flatMap((project) => [
    `Check on ${project.display_name}`,
    `What's changed in ${project.display_name} recently?`,
  ]);
}

/**
 * Cancel's copy (§6, ADR-010) — client-side-only cancellation, so the copy
 * is honest that a background completion is possible. **Do not strengthen
 * this** into a promise the system cannot keep; if the Architect ever wires
 * a real server-side abort, the Designer's simplified copy ("Cancelled.")
 * is a one-line change here, not a redesign.
 */
export const CANCELLED_NOTE =
  "You cancelled this. I'll stop showing progress for it — it won't appear as a reply, even if I finish it in the background.";

/** §5.3's second reassurance line, shown past 20s elapsed. */
export const REASSURANCE_LINE = "Still working — larger checks can take a little longer.";

const STAGE_LABELS: Record<StageName, string> = {
  message_received: "Received your message",
  context_loaded: "Loaded conversation context",
  memory_retrieved: "Checked memory",
  model_selected: "Selected a model for reasoning",
  llm_io: "Interpreted the request",
  plan_created: "Created a plan",
  agent_started: "Started the Project Manager Agent",
  tool_requested: "Requested a tool",
  permission_decision: "Checked permission",
  tool_result: "Received a result",
  agent_result: "Analysed the result",
  final_response: "Prepared your answer",
};

export function formatOffset(offsetMs: number): string {
  return `+${(offsetMs / 1000).toFixed(1)}s`;
}

/**
 * Turns one `trace[]` entry into the plain-English line `TraceDisclosure`
 * renders (M1_CHAT_SPEC.md §5.5's example table). The base label per stage
 * is fixed; a handful of stages additionally interpolate `detail` when it
 * looks like the field names the §5.5 example implies (e.g. "Created a
 * plan: check {Project} activity"). **`detail`'s shape is not part of §6's
 * frozen contract** (see `phases.ts`'s `dynamicLabelFromDetail` comment) —
 * this degrades to the fixed base label whenever the expected field isn't
 * present, rather than guess wrong.
 */
export function formatTraceStep(stage: StageName, offsetMs: number, detail?: unknown): TraceStep {
  return { label: describeStage(stage, detail), offset: formatOffset(offsetMs) };
}

function describeStage(stage: StageName, detail?: unknown): string {
  const record = detail && typeof detail === "object" ? (detail as Record<string, unknown>) : undefined;

  switch (stage) {
    case "model_selected": {
      const model = record?.model;
      return typeof model === "string" ? `Selected ${model} for reasoning` : STAGE_LABELS.model_selected;
    }
    case "plan_created": {
      const project = record?.project_display_name ?? record?.project;
      return typeof project === "string"
        ? `Created a plan: check ${project} activity`
        : STAGE_LABELS.plan_created;
    }
    case "tool_requested": {
      const tool = record?.tool ?? record?.operation;
      return typeof tool === "string" ? `Requested ${tool}` : STAGE_LABELS.tool_requested;
    }
    case "permission_decision": {
      const decision = record?.decision;
      return typeof decision === "string" ? `Permission: ${decision}` : STAGE_LABELS.permission_decision;
    }
    default:
      return STAGE_LABELS[stage];
  }
}
