/**
 * A test double with REAL commit/rollback semantics.
 *
 * Writes go to a staging buffer inside `$transaction`; the buffer is merged into the
 * committed store only if the callback resolves. If the callback throws — for any reason,
 * including a failed audit insert — the staged writes are discarded. That is precisely the
 * property `UnitOfWork.runAudited` depends on, so a unit test against this double proves the
 * helper's contract without a database.
 *
 * The equivalent assertion against real Postgres lives in `unit-of-work.integration.test.ts`
 * and runs when `SUNIL_TEST_DATABASE_URL` is set.
 */
export interface StoredRow {
  readonly table: string;
  readonly data: Record<string, unknown>;
}

export class FakeTransactionalDb {
  /** Rows that survived a commit. */
  readonly committed: StoredRow[] = [];
  /** Every write attempted, in order, whether or not it committed. */
  readonly writeLog: string[] = [];
  /** Set to make the next `auditLog.create` throw — simulates an audit-store failure. */
  failAuditWrite = false;
  /** Set to make `user.create` throw — simulates a domain-write failure. */
  failDomainWrite = false;

  transactionCount = 0;

  async $transaction<T>(fn: (tx: unknown) => Promise<T>): Promise<T> {
    this.transactionCount += 1;
    const staged: StoredRow[] = [];
    const tx = this.#makeTxClient(staged);
    const result = await fn(tx);
    // Commit only on resolution. A throw propagates and `staged` is discarded — rollback.
    this.committed.push(...staged);
    return result;
  }

  #makeTxClient(staged: StoredRow[]) {
    const write = (table: string, data: Record<string, unknown>) => {
      this.writeLog.push(table);
      const row = { table, data };
      staged.push(row);
      return Promise.resolve(data);
    };

    return {
      auditLog: {
        create: ({ data }: { data: Record<string, unknown> }) => {
          if (this.failAuditWrite) {
            this.writeLog.push("auditLog:FAILED");
            return Promise.reject(new Error("audit store unavailable"));
          }
          return write("auditLog", data);
        },
      },
      user: {
        create: ({ data }: { data: Record<string, unknown> }) => {
          if (this.failDomainWrite) {
            this.writeLog.push("user:FAILED");
            return Promise.reject(new Error("domain write failed"));
          }
          return write("user", data);
        },
        update: ({ data }: { data: Record<string, unknown> }) => write("user", data),
      },
      session: {
        updateMany: ({ data }: { data: Record<string, unknown> }) => write("session", data),
      },
    };
  }

  rowsIn(table: string): StoredRow[] {
    return this.committed.filter((row) => row.table === table);
  }
}
