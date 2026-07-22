/**
 * The guarded Prisma client (§9.3 layer 1, ADR-004).
 *
 * Warning §18.6: apps NEVER import `@prisma/client` directly — a dependency-cruiser fence
 * and an ESLint rule both enforce it. They import the client from here, so the append-only
 * guard cannot be bypassed by construction. The raw client is not exported.
 */
import { PrismaClient } from "@prisma/client";
import { InvariantViolationError } from "@sunil/core";

/** Thrown when anything tries to mutate an existing `audit_logs` row (FR-013/FR-052). */
export class AuditAppendOnlyError extends InvariantViolationError {
  constructor(operation: string) {
    super(`audit_logs is append-only — '${operation}' is not permitted`);
  }
}

/**
 * Operations refused against `AuditLog`. `create`/`createMany` are the only writes that
 * survive; everything that could alter or erase history is rejected before it reaches the
 * database (which rejects it a second time via the trigger — belt and braces).
 */
export const FORBIDDEN_AUDIT_OPERATIONS: ReadonlySet<string> = new Set([
  "update",
  "updateMany",
  "updateManyAndReturn",
  "upsert",
  "delete",
  "deleteMany",
]);

/**
 * `$allOperations` rather than a per-operation list: a future Prisma mutation verb is
 * refused by default instead of silently slipping through a hand-maintained allowlist.
 */
const auditAppendOnlyGuard = {
  name: "audit-append-only",
  query: {
    auditLog: {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      $allOperations({ operation, args, query }: any): Promise<unknown> {
        if (FORBIDDEN_AUDIT_OPERATIONS.has(operation)) {
          throw new AuditAppendOnlyError(operation);
        }
        return query(args) as Promise<unknown>;
      },
    },
  },
};

export interface CreatePrismaClientOptions {
  readonly datasourceUrl?: string;
  readonly log?: ("query" | "info" | "warn" | "error")[];
}

/**
 * Build the extended client. Extension order matters (§18.6): the append-only guard wraps
 * the client that every consumer receives.
 */
export function createPrismaClient(options: CreatePrismaClientOptions = {}) {
  const base = new PrismaClient({
    ...(options.datasourceUrl ? { datasourceUrl: options.datasourceUrl } : {}),
    ...(options.log ? { log: options.log } : {}),
  });
  return base.$extends(auditAppendOnlyGuard);
}

/** The client type every consumer handles. */
export type SunilPrismaClient = ReturnType<typeof createPrismaClient>;

/**
 * The client handed to code running inside an interactive transaction. It deliberately
 * lacks `$transaction`, so nested ad-hoc transactions are a type error (warning §18.2).
 */
export type TransactionClient = Omit<
  SunilPrismaClient,
  "$connect" | "$disconnect" | "$transaction" | "$extends"
>;

let singleton: SunilPrismaClient | undefined;

/** Process-wide client. Apps that manage their own lifecycle should call `createPrismaClient`. */
export function getPrismaClient(): SunilPrismaClient {
  singleton ??= createPrismaClient();
  return singleton;
}

export async function disconnectPrismaClient(): Promise<void> {
  if (singleton) {
    await singleton.$disconnect();
    singleton = undefined;
  }
}
