import type { WorkPhase } from "@/components/chat";

/**
 * The twelve NFR-020 stage names, in the frozen §6 contract's exact order.
 * `stage` is one of these on every `trace[]` entry and every SSE `stage`
 * event's `data.stage` — the API sends enums only (§11.2).
 */
export const STAGE_NAMES = [
  "message_received",
  "context_loaded",
  "memory_retrieved",
  "model_selected",
  "llm_io",
  "plan_created",
  "agent_started",
  "tool_requested",
  "permission_decision",
  "tool_result",
  "agent_result",
  "final_response",
] as const;

export type StageName = (typeof STAGE_NAMES)[number];

/** The 12→4 phase map (M1_CHAT_SPEC.md §5.3's stage table). */
const STAGE_TO_PHASE: Record<StageName, WorkPhase> = {
  message_received: "understanding",
  context_loaded: "understanding",
  memory_retrieved: "understanding",
  model_selected: "understanding",
  llm_io: "understanding",
  plan_created: "planning",
  agent_started: "working",
  tool_requested: "working",
  permission_decision: "working",
  tool_result: "working",
  agent_result: "finishing",
  final_response: "finishing",
};

export function phaseForStage(stage: StageName): WorkPhase {
  return STAGE_TO_PHASE[stage];
}

/**
 * Extracts the resolved project name from a stage event's `detail`, for
 * `WorkIndicator`'s "Checking {Project}…" substitution (§5.3).
 * `project_display_name` is a contracted key (`ARCHITECTURE_V1.md` §3.4),
 * but it is only carried on `plan_created` (the "planning" phase) — the
 * later "working"-phase stages (`agent_started`/`tool_requested`/
 * `permission_decision`/`tool_result`) don't repeat it. `useTurn` is what
 * remembers the last-known value across a turn and keeps supplying it once
 * the phase moves to "working"; this function only reads one event.
 */
export function dynamicLabelFromDetail(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object") return undefined;
  const record = detail as Record<string, unknown>;
  const candidate = record.project_display_name;
  return typeof candidate === "string" ? candidate : undefined;
}
