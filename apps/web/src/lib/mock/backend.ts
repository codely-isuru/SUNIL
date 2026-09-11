import type {
  ActivityResponse,
  Approval,
  ApprovalListResponse,
  ApprovalStatus,
  AuditTraceResponse,
  AuditTurnListResponse,
  DecisionRequest,
  ProjectListResponse,
  TaskListResponse,
} from "@/lib/types";
import {
  MOCK_ACTIVITY,
  MOCK_APPROVAL_EVENTS,
  MOCK_APPROVALS,
  MOCK_AUDIT_TURNS,
  MOCK_PROJECTS,
  MOCK_TASKS,
  MOCK_TRACE,
} from "./fixtures";

/**
 * The standalone mock backend: the OpenAPI shapes over the mockups' fixture
 * world, so the app runs with no FastAPI process (`NEXT_PUBLIC_SUNIL_DATA_SOURCE
 * = mock`, the default until integration). It is a *typed module*, not MSW:
 * one less runtime dependency in the browser bundle, and the seam is the
 * `apiCall` switch in `lib/api.ts`, which is what integration flips.
 *
 * It reproduces the server behaviours the UI has to survive:
 *
 * - the decision transition is guarded (`status = pending` AND not expired);
 *   a decision on anything else answers **409 with the current status**, which
 *   is the one path §6.7 says must never be papered over;
 * - decisions are terminal — deciding twice conflicts;
 * - list order is `created_at desc`, cursor-paged.
 */

let approvals: Approval[] = MOCK_APPROVALS.map((a) => ({ ...a }));

export class MockConflict extends Error {
  currentStatus: ApprovalStatus;

  constructor(currentStatus: ApprovalStatus, message: string) {
    super(message);
    this.currentStatus = currentStatus;
  }
}

export class MockNotFound extends Error {}

/** Test/dev helper — restores the fixture world. */
export function resetMockBackend() {
  approvals = MOCK_APPROVALS.map((a) => ({ ...a }));
}

function sweep(now = Date.now()) {
  // The server has an expiry sweeper (C4). Without this the mock would let an
  // owner "approve" a row whose countdown has visibly hit EXPIRED.
  approvals = approvals.map((a) =>
    a.status === "pending" && Date.parse(a.expires_at) <= now ? { ...a, status: "expired" } : a,
  );
}

export function mockListApprovals(params: {
  status?: ApprovalStatus;
  limit?: number;
  cursor?: string | null;
}): ApprovalListResponse {
  sweep();
  const ordered = [...approvals].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const filtered = params.status ? ordered.filter((a) => a.status === params.status) : ordered;
  const limit = params.limit ?? 50;
  const offset = params.cursor ? Number.parseInt(params.cursor, 10) || 0 : 0;
  const page = filtered.slice(offset, offset + limit);
  const nextOffset = offset + limit;
  return {
    approvals: page.map((a) => ({ ...a })),
    next_cursor: nextOffset < filtered.length ? String(nextOffset) : null,
  };
}

export function mockGetApproval(id: string): Approval {
  sweep();
  const found = approvals.find((a) => a.id === id);
  if (!found) throw new MockNotFound(`no approval ${id}`);
  return { ...found };
}

export function mockDecide(id: string, body: DecisionRequest): Approval {
  sweep();
  const index = approvals.findIndex((a) => a.id === id);
  if (index < 0) throw new MockNotFound(`no approval ${id}`);
  const row = approvals[index];

  // The C4 conditional UPDATE, guarded by status='pending'.
  if (row.status !== "pending") {
    throw new MockConflict(
      row.status,
      `approval is ${row.status}, not pending — the decision was not applied`,
    );
  }

  const decided: Approval = {
    ...row,
    status: body.decision === "approve" ? "approved" : "refused",
    decided_at: new Date().toISOString(),
    decided_by: "owner",
    decision_reason: body.reason?.trim() ? body.reason : null,
  };
  approvals[index] = decided;
  return { ...decided };
}

export function mockPendingCount(): number {
  sweep();
  return approvals.filter((a) => a.status === "pending").length;
}

export function mockListTasks(params: { limit?: number } = {}): TaskListResponse {
  const ordered = [...MOCK_TASKS].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const limit = params.limit ?? 50;
  return { tasks: ordered.slice(0, limit), next_cursor: null };
}

export function mockActivity(): ActivityResponse {
  return MOCK_ACTIVITY;
}

export function mockProjects(): ProjectListResponse {
  return { projects: MOCK_PROJECTS };
}

export function mockAuditIndex(params: { limit?: number } = {}): AuditTurnListResponse {
  const limit = params.limit ?? 50;
  return { turns: MOCK_AUDIT_TURNS.slice(0, limit), next_cursor: null };
}

export function mockAuditTrace(requestId: string): AuditTraceResponse {
  if (requestId !== MOCK_TRACE[0].detail?.request_id && requestId !== "01JQ8ZC2N4") {
    // Only the parked turn has a full fixture trace; anything else 404s rather
    // than inventing twelve stages that never happened.
    throw new MockNotFound(`no trace for ${requestId}`);
  }
  return { events: MOCK_TRACE, approval_events: MOCK_APPROVAL_EVENTS };
}
