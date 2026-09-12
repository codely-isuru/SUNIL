/**
 * Wire types for the V2 ops dashboard.
 *
 * Approvals (`Approval`, `ApprovalListResponse`, `DecisionRequest`,
 * `StateConflict`, `ErrorResponse`) are transcribed from the frozen
 * `docs/contracts/C4-approvals-openapi.yaml`. Nothing here may be widened
 * without a contract change.
 *
 * The ops-read shapes (`Task`, `ActivityResponse`, `AuditTurn`, `AuditEvent`)
 * are transcribed from the FROZEN `docs/contracts/C6-ops-reads-openapi.yaml`
 * v1.0.0 (2026-09-11) — spec §13.1–13.3 verbatim plus the Q2 `project_key`
 * ruling. `ProjectSummary` stays on C5/§13.4 (explicitly out of C6's scope,
 * C6 §7). Reconciled against C6 on merge; `src/lib/mock/c6-conformance.test.ts`
 * holds the mock layer to these key sets.
 *
 * House style, both contracts: every key is ALWAYS PRESENT; absence is `null`.
 * Optional (`?`) is therefore wrong for a C6 field and is not used below.
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

// ── C6 §13.1: tasks ──────────────────────────────────────────────────────────

export type TaskStatus = "pending" | "in_progress" | "completed" | "failed" | "parked";

export interface Task {
  id: string;
  /** UNTRUSTED — plan text derived from a user/LLM string (spec §7.2). */
  objective: string;
  status: TaskStatus;
  assigned_agent: string;
  /** `tasks.priority`; V2 writes `"normal"`. A trusted STRING, not a rank. */
  priority: string;
  /** Q2 ruling — written once at task creation, never updated. */
  project_key: string | null;
  request_id: string;
  conversation_id: string;
  approval_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  failure_kind: string | null;
}

/** `GET /api/v1/tasks/{task_id}` — the task plus its timeline (C6 §2.2). */
export interface TaskStatusEvent {
  /** Null on the creation event. */
  from_status: string | null;
  to_status: string;
  at: string;
}

export interface TaskDetail extends Task {
  /** Ascending `at`; ties keep write order. */
  status_events: TaskStatusEvent[];
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
  latest_stage: StageName | null;
  latest_stage_at: string | null;
  /**
   * The projection of the highest-seq audit row's `detail` onto EXACTLY these
   * three contracted keys (C6 §2.3). No other key passes — audit `detail` may
   * embed untrusted excerpts, and this projection is what keeps the endpoint's
   * trusted-detail promise true.
   */
  latest_detail: {
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
  /** `at` of the `final_response` row; null while the turn is in flight. */
  ended_at: string | null;
  /** Twelve-spine rows only — episode rows are not counted (C6 §2.4). */
  stage_count: number;
  outcome: "ok" | "failed" | "parked" | null;
  failure_kind: string | null;
  agent: string | null;
  /**
   * C6 returns the ID ONLY — there is no `conversation_label` on this shape,
   * so spec §10.1's "conversation" column renders the id. Recorded as a
   * fidelity deviation in `docs/tasks/S-D-web.md`.
   */
  conversation_id: string | null;
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
  task_id: string | null;
}

export interface AuditTraceResponse {
  events: AuditEvent[];
  /** Null when the turn had no approval episode (C6 §2.4). */
  approval_events: AuditEvent[] | null;
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
