/**
 * Wire types for the V2 ops dashboard.
 *
 * Approvals (`Approval`, `ApprovalListResponse`, `DecisionRequest`,
 * `StateConflict`, `ErrorResponse`) are transcribed from the frozen
 * `docs/contracts/C4-approvals-openapi.yaml`. Nothing here may be widened
 * without a contract change.
 *
 * The ops-read shapes (`Task`, `ActivityResponse`, `AuditTurn`, `AuditEvent`,
 * `ProjectSummary`) follow `V2_DASHBOARD_SPEC.md` §13.1–§13.4 — the C6
 * proposal the Architect is freezing on `task/S0-ops-contracts`. §13 states
 * the shapes are identical until C6 lands; when it does, this file is the one
 * place to reconcile.
 */

// ── C4: approvals ────────────────────────────────────────────────────────────

export type ApprovalStatus = "pending" | "approved" | "refused" | "expired" | "consumed";

export interface Approval {
  id: string;
  status: ApprovalStatus;
  created_at: string;
  expires_at: string;
  agent_id: string;
  tool: string;
  operation: string;
  args_hash: string;
  /** Redacted (ADR-006) params. Every VALUE is untrusted — C4 §4. */
  params_redacted: Record<string, unknown>;
  request_id: string;
  conversation_id: string;
  task_id: string;
  /** UNTRUSTED, ≤500 chars, plain text only — C4 §4. */
  summary: string;
  decided_at?: string | null;
  decided_by?: string | null;
  decision_reason?: string | null;
  consumed_at?: string | null;
}

export interface ApprovalListResponse {
  approvals: Approval[];
  next_cursor: string | null;
}

export interface DecisionRequest {
  decision: "approve" | "refuse";
  reason?: string;
}

export interface StateConflict {
  error: {
    kind: "state_conflict";
    message: string;
    current_status: ApprovalStatus;
  };
}

export type ErrorKind =
  | "unauthenticated"
  | "forbidden_client"
  | "not_found"
  | "validation_error";

export interface ErrorResponse {
  error: { kind: ErrorKind; message: string };
}

// ── C6 (proposed, spec §13): tasks ───────────────────────────────────────────

export type TaskStatus = "pending" | "in_progress" | "completed" | "failed" | "parked";

export interface Task {
  id: string;
  /** UNTRUSTED — plan text derived from a user/LLM string (spec §7.2). */
  objective: string;
  status: TaskStatus;
  assigned_agent: string;
  priority?: number | null;
  project_key?: string | null;
  request_id: string;
  conversation_id: string;
  approval_id?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  failure_kind?: string | null;
}

export interface TaskListResponse {
  tasks: Task[];
  next_cursor: string | null;
}

// ── C6 (proposed, spec §13.2): activity ──────────────────────────────────────

export type StageName =
  | "message_received"
  | "context_loaded"
  | "memory_retrieved"
  | "model_selected"
  | "llm_io"
  | "plan_created"
  | "agent_started"
  | "tool_requested"
  | "permission_decision"
  | "tool_result"
  | "agent_result"
  | "final_response";

export interface ActivityItem extends Task {
  latest_stage?: StageName | null;
  latest_stage_at?: string | null;
  latest_detail?: {
    project_display_name?: string;
    tool?: string;
    operation?: string;
  } | null;
}

export interface ActivityResponse {
  running: ActivityItem[];
  parked: ActivityItem[];
  recent: ActivityItem[];
}

// ── C6 (proposed, spec §13.3): audit ─────────────────────────────────────────

export interface AuditTurn {
  request_id: string;
  started_at: string;
  ended_at: string | null;
  stage_count: number;
  outcome: string | null;
  failure_kind: string | null;
  agent: string | null;
  conversation_id: string | null;
  conversation_label?: string | null;
  task_id: string | null;
}

export interface AuditTurnListResponse {
  turns: AuditTurn[];
  next_cursor: string | null;
}

export interface AuditEvent {
  seq: number;
  stage: StageName | string;
  actor: string;
  /** UNTRUSTED — may embed a truncated excerpt of outside content (T-32). */
  summary: string;
  detail: Record<string, unknown>;
  at: string;
  task_id?: string | null;
}

export interface AuditTraceResponse {
  events: AuditEvent[];
  approval_events?: AuditEvent[];
}

// ── C5 / §13.4: projects ─────────────────────────────────────────────────────

export interface ProjectSummary {
  key: string;
  display_name: string;
  last_activity_at?: string | null;
  open_tasks?: number | null;
  pending_approvals?: number | null;
}

export interface ProjectListResponse {
  projects: ProjectSummary[];
}
