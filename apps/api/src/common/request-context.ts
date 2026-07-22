/**
 * The request-scoped context (§9.4, NFR-012).
 *
 * One `AsyncLocalStorage` carries the correlation id, the resolved actor and — the point of
 * the exercise — the **audit tally**. Every `runAudited` call made through this app's
 * `AuditedUnitOfWork` increments it, and the global tally interceptor refuses to let a
 * successful mutating response leave the process with a tally of zero. Audit coverage is
 * therefore checked at run time, not remembered by a developer.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import type { ActorType } from "@sunil/core";
import type { RouteDeclaration } from "./declarations.js";
import type { ValidatedSession } from "../auth/session.types.js";

export interface ActorIdentity {
  readonly type: ActorType;
  readonly id: string | null;
  readonly label: string;
}

export const SYSTEM_ACTOR: ActorIdentity = {
  type: "SYSTEM",
  id: null,
  label: "system:api",
};

export const ANONYMOUS_ACTOR: ActorIdentity = {
  type: "HUMAN",
  id: null,
  label: "anonymous",
};

export interface RequestContext {
  readonly correlationId: string;
  readonly method: string;
  readonly path: string;
  ip: string | null;
  userAgent: string | null;
  actor: ActorIdentity;
  session: ValidatedSession | null;
  permissions: readonly string[] | null;
  declaration: RouteDeclaration | null;
  auditAction: string | null;
  /** Incremented by `AuditedUnitOfWork`; asserted by the tally interceptor (§9.4). */
  auditWrites: number;
  /** Set when a service already wrote the denial record, so the filter does not duplicate it. */
  denialAudited: boolean;
  /**
   * Set when an `Idempotency-Key` replayed a stored response. No mutation occurred, so the
   * §9.4 tally must not demand a NEW audit record — the original request already wrote one.
   */
  idempotentReplay: boolean;
}

const storage = new AsyncLocalStorage<RequestContext>();

export function runWithContext<T>(context: RequestContext, fn: () => T): T {
  return storage.run(context, fn);
}

export function currentContext(): RequestContext | undefined {
  return storage.getStore();
}

/**
 * Out-of-request callers (jobs, bootstrap) legitimately have no context; they get a SYSTEM
 * actor and a synthetic correlation id rather than a thrown error.
 */
export function currentActor(): ActorIdentity {
  return storage.getStore()?.actor ?? SYSTEM_ACTOR;
}

export function currentCorrelationId(fallback: string): string {
  return storage.getStore()?.correlationId ?? fallback;
}

/** Called by `AuditedUnitOfWork` — the single place the tally moves. */
export function noteAuditWrites(count: number): void {
  const context = storage.getStore();
  if (context) context.auditWrites += count;
}
