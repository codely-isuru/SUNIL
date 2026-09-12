import type {
  ActivityResponse,
  Approval,
  ApprovalListResponse,
  ApprovalStatus,
  AuditTraceResponse,
  AuditTurnListResponse,
  DecisionRequest,
  ErrorKind,
  ProjectListResponse,
  TaskListResponse,
} from "./types";
import {
  MockConflict,
  MockNotFound,
  mockActivity,
  mockAuditIndex,
  mockAuditTrace,
  mockDecide,
  mockGetApproval,
  mockListApprovals,
  mockListTasks,
  mockProjects,
} from "./mock/backend";

/**
 * The one client for the ops surfaces.
 *
 * ADR-008: the browser talks to FastAPI **directly**, cross-origin — no
 * Next.js rewrite, no route handler, no Server Action in front of it. Every
 * call carries `credentials: "include"` (the `sunil_session` cookie) and
 * `X-SUNIL-Client: web`.
 *
 * `NEXT_PUBLIC_API_BASE_URL` must be `http://localhost:8000` in dev, never
 * `127.0.0.1`: a host mismatch with the web origin silently withholds a
 * `SameSite=Lax` cookie (M1 lesson, carried forward).
 *
 * **Data source.** Until the API exists, the same functions serve the mock
 * backend. `NEXT_PUBLIC_SUNIL_DATA_SOURCE=api` (or `localStorage['sunil.dataSource']
 * = 'api'`, flipped from /settings) switches every read and the decision POST
 * to the real base URL. No component knows which is in play.
 */

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL && process.env.NEXT_PUBLIC_API_BASE_URL.length > 0
    ? process.env.NEXT_PUBLIC_API_BASE_URL
    : DEFAULT_API_BASE_URL;

const CLIENT_HEADER_VALUE = "web";

export type DataSource = "mock" | "api";

const DATA_SOURCE_KEY = "sunil.dataSource";

export function dataSource(): DataSource {
  if (typeof window !== "undefined") {
    const stored = window.localStorage.getItem(DATA_SOURCE_KEY);
    if (stored === "api" || stored === "mock") return stored;
  }
  return process.env.NEXT_PUBLIC_SUNIL_DATA_SOURCE === "api" ? "api" : "mock";
}

export function setDataSource(next: DataSource) {
  if (typeof window !== "undefined") window.localStorage.setItem(DATA_SOURCE_KEY, next);
}

// ── errors ───────────────────────────────────────────────────────────────────

export class ApiError extends Error {
  status: number;
  kind?: ErrorKind | string;

  constructor(status: number, message?: string, kind?: ErrorKind | string) {
    super(message ?? `API request failed with status ${status}`);
    this.status = status;
    this.kind = kind;
  }
}

/** 409 — the honest path C4 §5 designed for. Carries the server's truth. */
export class StateConflictError extends Error {
  currentStatus: ApprovalStatus;

  constructor(currentStatus: ApprovalStatus, message: string) {
    super(message);
    this.currentStatus = currentStatus;
  }
}

/** Network/DNS/CORS failure — "your decision didn't reach SUNIL" (§6.7). */
export class NetworkError extends Error {}

// ── transport ────────────────────────────────────────────────────────────────

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      credentials: "include",
      headers: {
        "X-SUNIL-Client": CLIENT_HEADER_VALUE,
        ...(init.headers ?? {}),
      },
    });
  } catch (cause) {
    throw new NetworkError(
      cause instanceof Error ? cause.message : "could not reach the SUNIL API",
    );
  }

  if (res.status === 409) {
    const body = (await res.json().catch(() => null)) as
      | { error?: { current_status?: ApprovalStatus; message?: string } }
      | null;
    throw new StateConflictError(
      body?.error?.current_status ?? "pending",
      body?.error?.message ?? "This approval is no longer pending.",
    );
  }

  if (!res.ok) {
    const body = (await res.json().catch(() => null)) as
      | { error?: { kind?: string; message?: string } }
      | null;
    throw new ApiError(res.status, body?.error?.message, body?.error?.kind);
  }

  return (await res.json()) as T;
}

/** Mock latency — enough to exercise skeletons and the submitting state. */
const MOCK_LATENCY_MS = 180;

async function mocked<T>(produce: () => T): Promise<T> {
  await new Promise((resolve) => setTimeout(resolve, MOCK_LATENCY_MS));
  try {
    return produce();
  } catch (err) {
    if (err instanceof MockConflict) throw new StateConflictError(err.currentStatus, err.message);
    if (err instanceof MockNotFound) throw new ApiError(404, err.message, "not_found");
    throw err;
  }
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") search.set(k, String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

// ── approvals (C4) ───────────────────────────────────────────────────────────

export interface ListApprovalsParams {
  status?: ApprovalStatus;
  limit?: number;
  cursor?: string | null;
}

export async function listApprovals(
  params: ListApprovalsParams = {},
): Promise<ApprovalListResponse> {
  if (dataSource() === "mock") return mocked(() => mockListApprovals(params));
  return request<ApprovalListResponse>(`/api/v1/approvals${query({ ...params })}`);
}

export async function getApproval(id: string): Promise<Approval> {
  if (dataSource() === "mock") return mocked(() => mockGetApproval(id));
  return request<Approval>(`/api/v1/approvals/${encodeURIComponent(id)}`);
}

export async function decideApproval(id: string, body: DecisionRequest): Promise<Approval> {
  if (dataSource() === "mock") return mocked(() => mockDecide(id, body));
  return request<Approval>(`/api/v1/approvals/${encodeURIComponent(id)}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ── ops reads (C6 proposal, spec §13) ────────────────────────────────────────

export async function listTasks(params: { limit?: number } = {}): Promise<TaskListResponse> {
  if (dataSource() === "mock") return mocked(() => mockListTasks(params));
  return request<TaskListResponse>(`/api/v1/tasks${query({ ...params })}`);
}

export async function getActivity(): Promise<ActivityResponse> {
  if (dataSource() === "mock") return mocked(() => mockActivity());
  return request<ActivityResponse>("/api/v1/activity");
}

export async function listProjects(): Promise<ProjectListResponse> {
  if (dataSource() === "mock") return mocked(() => mockProjects());
  return request<ProjectListResponse>("/api/v1/projects");
}

export async function listAuditTurns(
  params: { limit?: number } = {},
): Promise<AuditTurnListResponse> {
  if (dataSource() === "mock") return mocked(() => mockAuditIndex(params));
  return request<AuditTurnListResponse>(`/api/v1/audit${query({ ...params })}`);
}

export async function getAuditTrace(requestId: string): Promise<AuditTraceResponse> {
  if (dataSource() === "mock") return mocked(() => mockAuditTrace(requestId));
  return request<AuditTraceResponse>(`/api/v1/audit/${encodeURIComponent(requestId)}`);
}
