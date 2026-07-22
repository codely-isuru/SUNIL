/**
 * `system` queue processors (§12.1).
 *
 * Two maintenance jobs, both produced by durable Job Schedulers (never by an in-process
 * timer): `session-sweep` and `agent-staleness-sweep`.
 *
 * Both make security-relevant state changes, so both go through `UnitOfWork.runAudited` —
 * the audit record and the mutation commit together or not at all (ADR-005).
 */
import type { AuditEntry } from "@sunil/core";
import type { SessionRepository, SunilPrismaClient, UnitOfWork } from "@sunil/db";
import type { StaleAgentSweeper } from "@sunil/agents";
import type { AppLogger } from "../logger.js";

export interface SessionSweepDeps {
  readonly prisma: SunilPrismaClient;
  readonly sessions: SessionRepository;
  readonly uow: UnitOfWork;
  readonly logger: AppLogger;
  readonly now?: () => number;
}

export interface SessionSweepResult {
  readonly revoked: number;
  readonly sweptAt: string;
}

/**
 * Expire sessions past their idle or absolute deadline (§6.2). Expiry is enforced at
 * validation time regardless — this sweep keeps the table honest so the portal's session list
 * and the audit trail agree.
 */
export async function runSessionSweep(
  deps: SessionSweepDeps,
  correlationId: string,
): Promise<SessionSweepResult> {
  const at = new Date(deps.now?.() ?? Date.now());

  const due = await deps.prisma.session.count({
    where: {
      state: { in: ["ACTIVE", "PENDING_MFA"] },
      OR: [{ idleExpiresAt: { lt: at } }, { absoluteExpiresAt: { lt: at } }],
    },
  });

  // Nothing to revoke means no mutation, and a mutation-less audit record would be noise.
  if (due === 0) return { revoked: 0, sweptAt: at.toISOString() };

  const entry: AuditEntry = {
    actorType: "SYSTEM",
    actorId: null,
    actorLabel: "system:session-sweep",
    action: "auth.session.revoke",
    targetType: "session",
    targetId: null,
    after: { revoked: due, reason: "expired_sweep", sweptAt: at.toISOString() },
    outcome: "SUCCESS",
    correlationId,
  };

  const result = await deps.uow.runAudited(entry, (tx) => deps.sessions.markExpired(tx, at));

  deps.logger.info(
    { revoked: result.count, correlationId },
    "expired sessions revoked by the session sweep",
  );
  return { revoked: result.count, sweptAt: at.toISOString() };
}

export interface StalenessSweepDeps {
  readonly sweeper: StaleAgentSweeper;
  readonly logger: AppLogger;
}

/**
 * FR-073's out-of-process half. The sweeper itself lives in `@sunil/agents`; the worker's job
 * is to run it on the durable 60 s schedule and record the outcome.
 */
export async function runAgentStalenessSweep(
  deps: StalenessSweepDeps,
  correlationId: string,
): Promise<{ swept: number; agentIds: readonly string[] }> {
  const result = await deps.sweeper.sweep(correlationId);
  if (result.sweptAgentIds.length > 0) {
    deps.logger.warn(
      { agentIds: result.sweptAgentIds, correlationId },
      "stale agents marked FAILED by the staleness sweep",
    );
  }
  return { swept: result.sweptAgentIds.length, agentIds: result.sweptAgentIds };
}
