import type { StageName } from "./phases";

/**
 * The one client for the frozen §6 contract. ADR-008: the browser talks to
 * FastAPI directly, cross-origin — no Next.js rewrite/proxy, no Server
 * Actions, no route handlers standing in front of it. Every call carries
 * `credentials: "include"` (the session cookie) and `X-SUNIL-Client: web`.
 *
 * `NEXT_PUBLIC_API_BASE_URL` must be `http://localhost:8000` in dev, never
 * `127.0.0.1` — a mismatch with the web origin silently withholds the
 * session cookie (`SameSite=Lax` treats them as different sites). See
 * `scripts/dev-check.ps1`, which exists specifically to catch this.
 */
const DEFAULT_API_BASE_URL = "http://localhost:8000";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL && process.env.NEXT_PUBLIC_API_BASE_URL.length > 0
    ? process.env.NEXT_PUBLIC_API_BASE_URL
    : DEFAULT_API_BASE_URL;

const CLIENT_HEADER_VALUE = "web";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message?: string) {
    super(message ?? `API request failed with status ${status}`);
    this.status = status;
  }
}

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(`${API_BASE_URL}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "X-SUNIL-Client": CLIENT_HEADER_VALUE,
      ...(init.headers ?? {}),
    },
  });
}

// --- Auth (§6) ---

export interface SessionUser {
  id: string;
  name: string;
}

export interface SessionResponse {
  authenticated: boolean;
  user: SessionUser | null;
}

export async function login(username: string, password: string): Promise<{ user: SessionUser }> {
  const res = await apiFetch("/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!res.ok) throw new ApiError(res.status);
  return res.json();
}

export async function logout(): Promise<void> {
  await apiFetch("/api/v1/auth/logout", { method: "POST" });
}

export async function getSession(): Promise<SessionResponse> {
  const res = await apiFetch("/api/v1/auth/session");
  if (!res.ok) throw new ApiError(res.status);
  return res.json();
}

// --- Projects (§6, A-14 ruling 4) ---

interface ProjectsResponse {
  projects: KnownProject[];
}

/**
 * `GET /api/v1/projects` — the empty-state suggestion chips' only source
 * (M1_CHAT_SPEC.md §3). Deliberately never throws: on any failure (network,
 * a non-2xx, a session that has lapsed, malformed JSON) this resolves to
 * `[]`. **There is no hard-coded fallback list** — a product whose entire
 * claim is that it does not fabricate must not fabricate its own capability
 * list, so an empty result renders as no chips, never a stale guess.
 */
export async function getProjects(): Promise<KnownProject[]> {
  try {
    const res = await apiFetch("/api/v1/projects");
    if (!res.ok) return [];
    const data = (await res.json()) as ProjectsResponse;
    return Array.isArray(data.projects) ? data.projects : [];
  } catch {
    return [];
  }
}

// --- Chat turn (§6) ---

export interface ChatTraceEntry {
  stage: StageName;
  offset_ms: number;
  detail: unknown;
}

/**
 * The one project-list shape in the system (A-14, ruling 4): the same
 * element type `GET /api/v1/projects` returns and `failure.known_projects`
 * carries — one type, one renderer, two producers of one registry.
 */
export interface KnownProject {
  key: string;
  display_name: string;
}

export type ChatFailureKind = "provider_error" | "tool_failed" | "plan_rejected" | "unknown_project";

export interface ChatFailure {
  kind: ChatFailureKind;
  known_projects?: KnownProject[];
}

export interface ChatMessagePayload {
  id: string;
  role: "assistant";
  content: string;
  created_at: string;
}

export interface ChatTaskPayload {
  id: string;
  status: string;
  assigned_agent: string;
}

export interface ChatUsage {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface ChatResponse {
  request_id: string;
  conversation_id: string;
  outcome: "ok" | "failed";
  message: ChatMessagePayload | null;
  task: ChatTaskPayload | null;
  failure: ChatFailure | null;
  trace: ChatTraceEntry[];
  usage: ChatUsage;
}

export interface SendChatTurnArgs {
  message: string;
  conversationId: string | null;
  requestId: string;
  signal: AbortSignal;
}

/**
 * §11.3: a processed turn is HTTP 200 even when `outcome === "failed"` —
 * the HTTP transaction succeeded (authenticated, persisted, traced). Only
 * real transport-level facts (401/403/422/429/500) become `ApiError`.
 */
export async function sendChatTurn({
  message,
  conversationId,
  requestId,
  signal,
}: SendChatTurnArgs): Promise<ChatResponse> {
  const res = await apiFetch("/api/v1/chat", {
    method: "POST",
    signal,
    headers: {
      "Content-Type": "application/json",
      "X-Request-Id": requestId,
    },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });

  if (!res.ok) throw new ApiError(res.status);
  return res.json();
}

// --- Progress events (T12, optional — §6, ADR-009) ---

export interface StageEventPayload {
  stage: StageName;
  offset_ms: number;
  detail: unknown;
}

export interface ProgressEventHandlers {
  onStage: (event: StageEventPayload) => void;
  onError: () => void;
}

/**
 * Opens the optional SSE progress channel. `ARCHITECTURE_V1.md` §12:
 * "if `EventSource` errors or `SUNIL_PROGRESS_EVENTS` is off, `useTurn`
 * falls back to the deterministic client-side stepper." `SUNIL_PROGRESS_
 * EVENTS` is a backend-only flag (not `NEXT_PUBLIC_`-prefixed, §14.4), so
 * there is no client-visible way to know its value in advance — this
 * always attempts the connection and treats any error (including the
 * flag being off, however the backend signals that) identically: the
 * fallback stepper already running in `useTurn` is the whole recovery.
 * Returns a cleanup function; never throws.
 */
export function openProgressEvents(requestId: string, handlers: ProgressEventHandlers): () => void {
  let source: EventSource;
  try {
    source = new EventSource(`${API_BASE_URL}/api/v1/chat/${requestId}/events`, {
      withCredentials: true,
    });
  } catch {
    handlers.onError();
    return () => {};
  }

  source.addEventListener("stage", (event) => {
    try {
      const data = JSON.parse((event as MessageEvent<string>).data) as StageEventPayload;
      handlers.onStage(data);
    } catch {
      // Malformed event — ignore. The fallback schedule is the safety net.
    }
  });
  source.onerror = () => {
    handlers.onError();
  };

  return () => source.close();
}
