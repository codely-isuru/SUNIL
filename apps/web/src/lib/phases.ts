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
 * Best-effort project/tool name extraction from a stage event's `detail`
 * payload, for `WorkIndicator`'s "Checking {Project}…" substitution
 * (§5.3). **`detail`'s shape per stage is not specified by §6's frozen
 * contract** — this is a guess at plausible field names, not a documented
 * schema, and degrades to `undefined` (the generic "Working on it…" copy)
 * rather than assume a shape that turns out wrong. Flagged to the
 * Delivery Manager as an open question on the contract.
 */
export function dynamicLabelFromDetail(detail: unknown): string | undefined {
  if (!detail || typeof detail !== "object") return undefined;
  const record = detail as Record<string, unknown>;
  const candidate = record.project_display_name ?? record.display_name ?? record.project;
  return typeof candidate === "string" ? candidate : undefined;
}
