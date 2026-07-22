/**
 * `@sunil/db` — schema, guarded client, audit service, UnitOfWork, repositories, bootstrap.
 *
 * Depends on `@sunil/core` only (DAG §3.2). Apps import the client from HERE, never from
 * `@prisma/client` directly (§18.6).
 */
export {
  AuditAppendOnlyError,
  FORBIDDEN_AUDIT_OPERATIONS,
  createPrismaClient,
  disconnectPrismaClient,
  getPrismaClient,
  type CreatePrismaClientOptions,
  type SunilPrismaClient,
  type TransactionClient,
} from "./client.js";

export {
  AuditService,
  type AuditFallbackLogger,
  type AuditLog,
  type AuditRecord,
  type AuditServiceContract,
} from "./audit/audit-service.js";

export {
  UnitOfWork,
  type AuditSpec,
  type TransactionRunner,
  type UnitOfWorkOptions,
} from "./unit-of-work.js";

export {
  ARGON2_OPTIONS,
  getDummyPasswordHash,
  hashPassword,
  verifyPassword,
} from "./password.js";

export * from "./repositories/identity.js";
export * from "./repositories/platform.js";

export { bootstrap, type BootstrapDeps, type BootstrapReport } from "./bootstrap/seed.js";

/**
 * Prisma's generated enums and namespace, re-exported so apps get them without importing
 * `@prisma/client` and tripping the dependency fence.
 */
export { Prisma } from "@prisma/client";
export type {
  ActorType,
  AgentStatus,
  AuditOutcome,
  EnvelopeType,
  JobOutcome,
  MfaStatus,
  ProviderVerification,
  SessionState,
  UserStatus,
} from "@prisma/client";
