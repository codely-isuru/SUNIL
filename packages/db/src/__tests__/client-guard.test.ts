/**
 * §9.3 layer 1 — the Prisma client extension that makes `audit_logs` append-only in the
 * application. Layer 2 (the database trigger) is proven by the integration spec.
 *
 * These assertions need no database: the guard throws before the query reaches the engine.
 */
import { describe, expect, it } from "vitest";
import {
  AuditAppendOnlyError,
  FORBIDDEN_AUDIT_OPERATIONS,
  createPrismaClient,
} from "../client.js";

/** Deliberately a closed port: any query that gets past the guard fails fast, visibly. */
const UNREACHABLE_DSN = "postgresql://sunil@127.0.0.1:1/sunil_guard_test";

const prisma = createPrismaClient({ datasourceUrl: UNREACHABLE_DSN });

describe("audit_logs append-only guard (§9.3 / FR-013 / FR-052)", () => {
  it("refuses update", async () => {
    await expect(
      prisma.auditLog.update({ where: { id: "any" }, data: { action: "tampered" } }),
    ).rejects.toBeInstanceOf(AuditAppendOnlyError);
  });

  it("refuses updateMany", async () => {
    await expect(
      prisma.auditLog.updateMany({ where: {}, data: { action: "tampered" } }),
    ).rejects.toBeInstanceOf(AuditAppendOnlyError);
  });

  it("refuses delete", async () => {
    await expect(prisma.auditLog.delete({ where: { id: "any" } })).rejects.toBeInstanceOf(
      AuditAppendOnlyError,
    );
  });

  it("refuses deleteMany", async () => {
    await expect(prisma.auditLog.deleteMany({ where: {} })).rejects.toBeInstanceOf(
      AuditAppendOnlyError,
    );
  });

  it("refuses upsert", async () => {
    await expect(
      prisma.auditLog.upsert({
        where: { id: "any" },
        create: {
          actorType: "SYSTEM",
          actorLabel: "system:test",
          action: "system.bootstrap",
          outcome: "SUCCESS",
          correlationId: "c",
        },
        update: { action: "tampered" },
      }),
    ).rejects.toBeInstanceOf(AuditAppendOnlyError);
  });

  it("names the refused operation in the error", async () => {
    const error = (await prisma.auditLog
      .delete({ where: { id: "any" } })
      .catch((e: unknown) => e)) as Error;
    expect(error.message).toContain("append-only");
    expect(error.message).toContain("delete");
  });

  it("does not block reads or appends", () => {
    for (const allowed of ["create", "createMany", "findMany", "findUnique", "count"]) {
      expect(FORBIDDEN_AUDIT_OPERATIONS.has(allowed)).toBe(false);
    }
  });

  it("does not apply the guard to other models (negative control)", async () => {
    // Reaches the engine and fails on connectivity — which proves the guard let it past.
    const error = (await prisma.user
      .update({ where: { id: "any" }, data: { displayName: "x" } })
      .catch((e: unknown) => e)) as Error;
    expect(error).not.toBeInstanceOf(AuditAppendOnlyError);
  });
});
