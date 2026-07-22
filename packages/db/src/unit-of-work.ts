/**
 * `UnitOfWork.runAudited` — the audit-before-commit primitive (§9.2, ADR-005, Gate 1).
 *
 * THE RULE (warning §18.2): every security-relevant mutation runs through here. Never call
 * `prisma.$transaction` ad hoc for a mutation — a mutation that bypasses this helper is not
 * covered by audit-before-commit, and the runtime coverage tally in `apps/api` will throw.
 *
 * The guarantee this file exists to provide:
 *
 *     domain writes  ─┐
 *                     ├── ONE interactive transaction ── commit
 *     audit record   ─┘   (audit is the LAST write)
 *
 * If the audit insert fails, the whole transaction rolls back: the mutation never happened
 * and the caller gets a generic 500. Neither the mutation nor its audit record can exist
 * without the other. That is structural, and `unit-of-work.test.ts` proves it rather than
 * asserting it.
 */
import { AuditWriteFailedError, type AuditEntry } from "@sunil/core";
import type { AuditServiceContract } from "./audit/audit-service.js";
import type { SunilPrismaClient, TransactionClient } from "./client.js";

/**
 * The audit entry (or entries) for a mutation. A function form lets the spec reference
 * values that only exist after the domain writes — e.g. the id of a row created inside the
 * transaction, or the before/after permission sets of §6.6.
 */
export type AuditSpec<T> =
  | AuditEntry
  | readonly AuditEntry[]
  | ((result: T, tx: TransactionClient) => AuditEntry | readonly AuditEntry[] | Promise<AuditEntry | readonly AuditEntry[]>);

export interface UnitOfWorkOptions {
  /** Interactive-transaction ceiling, ms. */
  readonly timeoutMs?: number;
  /** How long to wait for a connection from the pool, ms. */
  readonly maxWaitMs?: number;
}

/**
 * Minimal transaction-running surface. Declared as an interface so tests can substitute a
 * store with real commit/rollback semantics without a database.
 */
export interface TransactionRunner {
  $transaction<T>(
    fn: (tx: TransactionClient) => Promise<T>,
    options?: { timeout?: number; maxWait?: number },
  ): Promise<T>;
}

export class UnitOfWork {
  readonly #runner: TransactionRunner;
  readonly #audit: AuditServiceContract;
  readonly #options: Required<UnitOfWorkOptions>;

  constructor(
    runner: TransactionRunner | SunilPrismaClient,
    audit: AuditServiceContract,
    options: UnitOfWorkOptions = {},
  ) {
    this.#runner = runner as TransactionRunner;
    this.#audit = audit;
    this.#options = {
      timeoutMs: options.timeoutMs ?? 15_000,
      maxWaitMs: options.maxWaitMs ?? 5_000,
    };
  }

  /**
   * Run domain writes and their audit record(s) in ONE transaction, audit last.
   *
   * @throws AuditWriteFailedError if the audit insert fails — thrown from INSIDE the
   *         transaction callback, so the domain writes roll back with it.
   */
  async runAudited<T>(
    spec: AuditSpec<T>,
    fn: (tx: TransactionClient) => Promise<T>,
  ): Promise<T> {
    return this.#runner.$transaction(
      async (tx) => {
        const result = await fn(tx);

        const resolved = typeof spec === "function" ? await spec(result, tx) : spec;
        const entries: readonly AuditEntry[] = Array.isArray(resolved)
          ? (resolved as readonly AuditEntry[])
          : [resolved as AuditEntry];

        if (entries.length === 0) {
          // A mutation with no audit entry is exactly the failure mode ADR-005 prevents.
          throw new AuditWriteFailedError("runAudited requires at least one audit entry");
        }

        try {
          for (const entry of entries) {
            await this.#audit.record(tx, entry);
          }
        } catch (cause) {
          throw new AuditWriteFailedError("Operation not recorded", { cause });
        }

        return result;
      },
      { timeout: this.#options.timeoutMs, maxWait: this.#options.maxWaitMs },
    );
  }

  /**
   * Read-only work needing transactional consistency. Deliberately separate and deliberately
   * named: if you reach for this to perform a mutation you are bypassing the audit rule.
   */
  async runReadOnly<T>(fn: (tx: TransactionClient) => Promise<T>): Promise<T> {
    return this.#runner.$transaction(fn, {
      timeout: this.#options.timeoutMs,
      maxWait: this.#options.maxWaitMs,
    });
  }
}
