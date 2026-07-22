/**
 * The ports the runtime depends on.
 *
 * These are the SUBSET of `@sunil/db` each collaborator actually uses. The real
 * `AgentRepository`, `AgentMessageRepository` and `UnitOfWork` satisfy them structurally, so
 * production wiring passes the real objects and nothing is duplicated — but the runtime is
 * expressed against behaviour rather than against classes carrying private fields, which is
 * what lets the unit tests substitute a store with real transaction semantics.
 *
 * `runAudited` is deliberately the ONLY mutation entry point exposed here: there is no port
 * that would let the runtime mutate outside an audited transaction (ADR-005 / §18.2).
 */
import type { Agent, AgentMessage, AuditSpec, Prisma, TransactionClient } from "@sunil/db";

export interface AgentStore {
  findById(id: string): Promise<Agent | null>;
  update(tx: TransactionClient, id: string, data: Prisma.AgentUpdateInput): Promise<Agent>;
  /** Heartbeat bookkeeping — not a security mutation, deliberately not audited (§11.3). */
  recordHeartbeat(id: string, at: Date): Promise<Agent>;
  /** RUNNING agents whose last heartbeat is older than their own configured threshold. */
  findStale(now: Date): Promise<Agent[]>;
}

export interface AgentMessageStore {
  append(tx: TransactionClient, data: Prisma.AgentMessageCreateInput): Promise<AgentMessage>;
}

export interface AuditedRunner {
  runAudited<T>(spec: AuditSpec<T>, fn: (tx: TransactionClient) => Promise<T>): Promise<T>;
}
