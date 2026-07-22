/**
 * The Gate-1 guarantee, proven rather than asserted:
 *
 *   "A failed audit write FAILS the request — the mutation can never commit unaudited."
 *
 * These tests drive the real `UnitOfWork` and the real `AuditService` against a double with
 * genuine commit/rollback semantics (`FakeTransactionalDb`).
 */
import { beforeEach, describe, expect, it } from "vitest";
import { AuditWriteFailedError, type AuditEntry } from "@sunil/core";
import { AuditService } from "../audit/audit-service.js";
import type { SunilPrismaClient, TransactionClient } from "../client.js";
import { UnitOfWork } from "../unit-of-work.js";
import { FakeTransactionalDb } from "./fake-transactional-db.js";

const entry: AuditEntry = {
  actorType: "HUMAN",
  actorId: "018f4a9e-0000-7000-8000-000000000001",
  actorLabel: "owner@example.test",
  action: "user.create",
  targetType: "user",
  targetId: "018f4a9e-0000-7000-8000-0000000000ff",
  outcome: "SUCCESS",
  correlationId: "corr-uow-1",
};

describe("UnitOfWork.runAudited (§9.2 / ADR-005)", () => {
  let db: FakeTransactionalDb;
  let uow: UnitOfWork;

  beforeEach(() => {
    db = new FakeTransactionalDb();
    const audit = new AuditService(db as unknown as SunilPrismaClient);
    uow = new UnitOfWork(db as unknown as SunilPrismaClient, audit);
  });

  it("commits the mutation and its audit record together", async () => {
    const result = await uow.runAudited(entry, async (tx: TransactionClient) => {
      await (tx as unknown as { user: { create: (a: unknown) => Promise<unknown> } }).user.create({
        data: { email: "new@example.test" },
      });
      return "created";
    });

    expect(result).toBe("created");
    expect(db.rowsIn("user")).toHaveLength(1);
    expect(db.rowsIn("auditLog")).toHaveLength(1);
    expect(db.transactionCount).toBe(1);
  });

  it("appends the audit record as the LAST write in the transaction", async () => {
    await uow.runAudited(entry, async (tx: TransactionClient) => {
      const t = tx as unknown as { user: { create: (a: unknown) => Promise<unknown> } };
      await t.user.create({ data: { email: "a@example.test" } });
      await t.user.create({ data: { email: "b@example.test" } });
    });

    expect(db.writeLog).toEqual(["user", "user", "auditLog"]);
  });

  it("ROLLS BACK the mutation when the audit write fails", async () => {
    db.failAuditWrite = true;

    await expect(
      uow.runAudited(entry, async (tx: TransactionClient) => {
        await (
          tx as unknown as { user: { create: (a: unknown) => Promise<unknown> } }
        ).user.create({ data: { email: "never@example.test" } });
        return "should not survive";
      }),
    ).rejects.toBeInstanceOf(AuditWriteFailedError);

    // The whole point: the domain write did not commit.
    expect(db.committed).toHaveLength(0);
    expect(db.rowsIn("user")).toHaveLength(0);
    expect(db.rowsIn("auditLog")).toHaveLength(0);
    // …but it WAS attempted, so this is a rollback, not a short-circuit that skipped it.
    expect(db.writeLog).toEqual(["user", "auditLog:FAILED"]);
  });

  it("surfaces the audit failure as a generic 'Operation not recorded' error", async () => {
    db.failAuditWrite = true;
    const error = await uow
      .runAudited(entry, async () => "x")
      .catch((e: unknown) => e as AuditWriteFailedError);

    expect(error).toBeInstanceOf(AuditWriteFailedError);
    expect((error as AuditWriteFailedError).message).toBe("Operation not recorded");
    expect((error as AuditWriteFailedError).httpStatus).toBe(500);
  });

  it("writes no audit record when the domain write fails", async () => {
    db.failDomainWrite = true;

    await expect(
      uow.runAudited(entry, async (tx: TransactionClient) => {
        await (
          tx as unknown as { user: { create: (a: unknown) => Promise<unknown> } }
        ).user.create({ data: { email: "never@example.test" } });
      }),
    ).rejects.toThrow("domain write failed");

    expect(db.committed).toHaveLength(0);
    expect(db.writeLog).toEqual(["user:FAILED"]);
  });

  it("refuses a mutation that supplies no audit entry at all", async () => {
    await expect(
      uow.runAudited([], async (tx: TransactionClient) => {
        await (
          tx as unknown as { user: { create: (a: unknown) => Promise<unknown> } }
        ).user.create({ data: { email: "unaudited@example.test" } });
      }),
    ).rejects.toBeInstanceOf(AuditWriteFailedError);

    expect(db.committed).toHaveLength(0);
  });

  it("accepts a spec function so the entry can reference values created in the transaction", async () => {
    await uow.runAudited<{ id: string }>(
      (result) => ({ ...entry, targetId: result.id }),
      async (tx: TransactionClient) => {
        await (
          tx as unknown as { user: { create: (a: unknown) => Promise<unknown> } }
        ).user.create({ data: { email: "c@example.test" } });
        return { id: "created-id-42" };
      },
    );

    const audit = db.rowsIn("auditLog")[0];
    expect(audit?.data["targetId"]).toBe("created-id-42");
  });

  it("writes several audit records atomically when a mutation needs more than one", async () => {
    await uow.runAudited([entry, { ...entry, action: "auth.session.revoke" }], async () => "ok");
    expect(db.rowsIn("auditLog")).toHaveLength(2);
  });
});
