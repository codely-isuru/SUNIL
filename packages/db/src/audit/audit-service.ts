/**
 * The audit service (§9.1, ADR-005).
 *
 * `prisma.auditLog.create` is callable ONLY from inside this file — a dependency-cruiser
 * path rule and an ESLint fence both enforce it (§9.4). That is what guarantees every
 * record gets a server-generated timestamp and redacted payloads: there is no other door.
 */
import type { AuditLog, Prisma } from "@prisma/client";
import {
  AuditEntrySchema,
  DenialEntrySchema,
  redact,
  type AuditEntry,
  type AuditFilter,
  type DenialEntry,
  type PageRequest,
  type Paged,
} from "@sunil/core";
import type { SunilPrismaClient, TransactionClient } from "../client.js";

/** The §5.4 audit group model. `AuditRecord` is the domain-facing alias. */
export type { AuditLog };
export type AuditRecord = AuditLog;

/**
 * Minimal logger seam. `packages/db` does not own a logging stack; apps inject Pino.
 * Used for exactly one thing: the ADR-005 §2 asymmetry — a failed DENIAL write is a
 * `fatal` operational alert, but it never converts into an authorisation bypass.
 */
export interface AuditFallbackLogger {
  fatal(context: Record<string, unknown>, message: string): void;
}

const defaultFallbackLogger: AuditFallbackLogger = {
  fatal(context, message) {
    // eslint-disable-next-line no-console -- last-resort channel when the audit store is unavailable
    console.error(JSON.stringify({ level: "fatal", msg: message, ...context }));
  },
};

export interface AuditServiceContract {
  /** Inside a mutation transaction. The UnitOfWork appends this as the LAST write. */
  record(tx: TransactionClient, entry: AuditEntry): Promise<void>;
  /** Outside any transaction — a denial has no domain mutation to protect (§9.2). */
  recordDenial(entry: DenialEntry): Promise<void>;
  query(filter: AuditFilter, page: PageRequest): Promise<Paged<AuditRecord>>;
}

/** Convert a redacted payload into something Prisma will accept as JSON. */
function toJsonInput(value: unknown): Prisma.InputJsonValue | undefined {
  if (value === null || value === undefined) return undefined;
  return JSON.parse(JSON.stringify(redact(value))) as Prisma.InputJsonValue;
}

export class AuditService implements AuditServiceContract {
  readonly #prisma: SunilPrismaClient;
  readonly #logger: AuditFallbackLogger;

  constructor(prisma: SunilPrismaClient, logger: AuditFallbackLogger = defaultFallbackLogger) {
    this.#prisma = prisma;
    this.#logger = logger;
  }

  /**
   * Write one audit record inside the caller's transaction.
   *
   * There is no timestamp parameter: `createdAt` comes from the database default, so a
   * caller cannot backdate or forge an entry (FR-050).
   */
  async record(tx: TransactionClient, entry: AuditEntry): Promise<void> {
    const parsed = AuditEntrySchema.parse(entry);
    const before = toJsonInput(parsed.before);
    const after = toJsonInput(parsed.after);

    await tx.auditLog.create({
      data: {
        actorType: parsed.actorType,
        actorId: parsed.actorId ?? null,
        actorLabel: parsed.actorLabel,
        action: parsed.action,
        targetType: parsed.targetType ?? null,
        targetId: parsed.targetId ?? null,
        ...(before === undefined ? {} : { before }),
        ...(after === undefined ? {} : { after }),
        outcome: parsed.outcome,
        denialReason: parsed.denialReason ?? null,
        correlationId: parsed.correlationId,
        ip: parsed.ip ?? null,
        userAgent: parsed.userAgent ?? null,
      },
    });
  }

  /**
   * ADR-005 §2, the deliberate asymmetry: if this write fails the denial STILL STANDS.
   * Default-deny is never weakened to preserve a log line; the failure is raised as a
   * `fatal` log carrying the correlation id, which is an operational alert condition.
   */
  async recordDenial(entry: DenialEntry): Promise<void> {
    const parsed = DenialEntrySchema.parse(entry);
    try {
      await this.record(this.#prisma, {
        ...parsed,
        before: parsed.before ?? null,
        after: parsed.after ?? null,
      });
    } catch (error) {
      this.#logger.fatal(
        {
          correlationId: parsed.correlationId,
          action: parsed.action,
          denialReason: parsed.denialReason,
          error: error instanceof Error ? error.message : "unknown",
        },
        "audit denial record could not be written; the denial still stands",
      );
    }
  }

  /** Reverse-chronological, paged. Payloads were redacted at write time (FR-053). */
  async query(filter: AuditFilter, page: PageRequest): Promise<Paged<AuditRecord>> {
    const where: Prisma.AuditLogWhereInput = {};
    if (filter.actorId) where.actorId = filter.actorId;
    if (filter.actorType) where.actorType = filter.actorType;
    if (filter.action) where.action = filter.action;
    if (filter.targetType) where.targetType = filter.targetType;
    if (filter.targetId) where.targetId = filter.targetId;
    if (filter.outcome) where.outcome = filter.outcome;
    if (filter.correlationId) where.correlationId = filter.correlationId;
    if (filter.from || filter.to) {
      where.createdAt = {
        ...(filter.from ? { gte: filter.from } : {}),
        ...(filter.to ? { lte: filter.to } : {}),
      };
    }

    const skip = (page.page - 1) * page.pageSize;
    const [items, total] = await Promise.all([
      this.#prisma.auditLog.findMany({
        where,
        orderBy: { createdAt: "desc" },
        skip,
        take: page.pageSize,
      }),
      this.#prisma.auditLog.count({ where }),
    ]);

    return {
      items,
      page: page.page,
      pageSize: page.pageSize,
      total,
      hasMore: skip + items.length < total,
    };
  }
}
