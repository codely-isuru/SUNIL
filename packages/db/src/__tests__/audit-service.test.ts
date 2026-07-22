import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuditService, type AuditFallbackLogger } from "../audit/audit-service.js";
import type { SunilPrismaClient, TransactionClient } from "../client.js";

describe("AuditService.record (§9.1)", () => {
  let service: AuditService;
  let captured: Record<string, unknown>[];

  const collector = () =>
    ({
      auditLog: {
        create: ({ data }: { data: Record<string, unknown> }) => {
          captured.push(data);
          return Promise.resolve(data);
        },
      },
    }) as unknown as SunilPrismaClient;

  const tx = (): TransactionClient => collector() as unknown as TransactionClient;

  beforeEach(() => {
    captured = [];
    service = new AuditService(collector());
  });

  it("never persists a caller-supplied timestamp (FR-050)", async () => {
    await service.record(tx(), {
      actorType: "HUMAN",
      actorLabel: "owner@example.test",
      action: "user.update",
      correlationId: "corr-1",
      // @ts-expect-error — there is deliberately no timestamp field on AuditEntry
      createdAt: new Date("1999-01-01"),
    });

    expect(captured[0]).not.toHaveProperty("createdAt");
  });

  it("redacts before/after payloads before they are persisted (§9.5)", async () => {
    await service.record(tx(), {
      actorType: "HUMAN",
      actorLabel: "owner@example.test",
      action: "user.update",
      correlationId: "corr-2",
      before: { email: "a@example.test", passwordHash: "$argon2id$v=19$m=19456,t=2,p=1$abc" },
      after: { email: "a@example.test", apiKey: "sk-ant-0123456789abcdefghij" },
    });

    const row = captured[0] ?? {};
    expect(JSON.stringify(row["before"])).not.toContain("argon2id");
    expect(JSON.stringify(row["before"])).toContain("[REDACTED]");
    expect(JSON.stringify(row["after"])).not.toContain("0123456789abcdefghij");
  });

  it("rejects an action outside the catalogue rather than writing a free-text verb", async () => {
    await expect(
      service.record(tx(), {
        actorType: "SYSTEM",
        actorLabel: "system:test",
        // @ts-expect-error — not in the AUDIT_ACTIONS catalogue
        action: "user.obliterate",
        correlationId: "corr-3",
      }),
    ).rejects.toThrow();
  });

  it("records a non-human actor (FR-013)", async () => {
    await service.record(tx(), {
      actorType: "AGENT",
      actorId: "018f4a9e-0000-7000-8000-0000000000aa",
      actorLabel: "agent:email-triage",
      action: "agent.run",
      correlationId: "corr-4",
    });
    expect(captured[0]?.["actorType"]).toBe("AGENT");
    expect(captured[0]?.["actorId"]).toBe("018f4a9e-0000-7000-8000-0000000000aa");
  });
});

describe("AuditService.recordDenial — the ADR-005 asymmetry", () => {
  it("does NOT throw when the denial record cannot be written, and raises a fatal log", async () => {
    const fatal = vi.fn();
    const logger: AuditFallbackLogger = { fatal };
    const failing = {
      auditLog: {
        create: () => Promise.reject(new Error("audit store unavailable")),
      },
    } as unknown as SunilPrismaClient;

    const service = new AuditService(failing, logger);

    // The denial still stands: default-deny is never weakened to preserve a log line.
    await expect(
      service.recordDenial({
        actorType: "HUMAN",
        actorLabel: "anonymous",
        action: "auth.denied",
        denialReason: "forbidden",
        correlationId: "corr-denial-1",
      }),
    ).resolves.toBeUndefined();

    expect(fatal).toHaveBeenCalledTimes(1);
    const [context] = fatal.mock.calls[0] as [Record<string, unknown>, string];
    expect(context["correlationId"]).toBe("corr-denial-1");
  });

  it("forces FAILURE outcome and a category-only reason", async () => {
    const captured: Record<string, unknown>[] = [];
    const prisma = {
      auditLog: {
        create: ({ data }: { data: Record<string, unknown> }) => {
          captured.push(data);
          return Promise.resolve(data);
        },
      },
    } as unknown as SunilPrismaClient;

    await new AuditService(prisma).recordDenial({
      actorType: "HUMAN",
      actorLabel: "anonymous",
      action: "auth.denied",
      denialReason: "csrf",
      correlationId: "corr-denial-2",
    });

    expect(captured[0]?.["outcome"]).toBe("FAILURE");
    expect(captured[0]?.["denialReason"]).toBe("csrf");
  });
});
