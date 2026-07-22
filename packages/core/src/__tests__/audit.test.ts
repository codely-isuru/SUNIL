import { describe, expect, it } from "vitest";
import { AUDIT_ACTIONS, AuditEntrySchema, DenialEntrySchema, isAuditAction } from "../audit.js";

describe("audit contracts (§9.1 / FR-050)", () => {
  it("offers the caller NO way to supply a timestamp", () => {
    const keys = Object.keys(AuditEntrySchema.shape);
    for (const forbidden of ["createdAt", "timestamp", "occurredAt", "at", "time"]) {
      expect(keys).not.toContain(forbidden);
    }
  });

  it("strips a caller-supplied timestamp instead of honouring it", () => {
    const parsed = AuditEntrySchema.parse({
      actorType: "HUMAN",
      actorId: "018f4a9e-0000-7000-8000-000000000001",
      actorLabel: "owner@example.test",
      action: "user.update",
      outcome: "SUCCESS",
      correlationId: "corr-1",
      createdAt: "1999-01-01T00:00:00.000Z",
    });
    expect(parsed).not.toHaveProperty("createdAt");
  });

  it("has a de-duplicated action catalogue", () => {
    expect(new Set(AUDIT_ACTIONS).size).toBe(AUDIT_ACTIONS.length);
    for (const action of AUDIT_ACTIONS) {
      expect(action).toMatch(/^[a-z]+(\.[a-z]+)+$/);
    }
  });

  it("carries a verb for each repeatable-schedule boot action (ADR-010)", () => {
    expect(AUDIT_ACTIONS).toContain("job.scheduler.register");
    expect(AUDIT_ACTIONS).toContain("job.scheduler.reconcile");

    // Registration and reconciliation are distinguishable in the log: one verb for both
    // would make "a definition was removed" look like "a definition was re-registered".
    expect("job.scheduler.register").not.toBe("job.scheduler.reconcile");

    for (const action of ["job.scheduler.register", "job.scheduler.reconcile"] as const) {
      expect(
        AuditEntrySchema.safeParse({
          actorType: "SYSTEM",
          actorLabel: "system:scheduler",
          action,
          targetType: "job_scheduler",
          targetId: "system:session-sweep",
          correlationId: "corr-sched-1",
        }).success,
      ).toBe(true);
    }
  });

  it("still accepts system.bootstrap, so the existing scheduler call site is unbroken", () => {
    // The new verbs are additive. Routing the scheduler onto them is a separate change.
    expect(isAuditAction("system.bootstrap")).toBe(true);
    expect(
      AuditEntrySchema.safeParse({
        actorType: "SYSTEM",
        actorLabel: "system:scheduler",
        action: "system.bootstrap",
        targetType: "job_scheduler",
        correlationId: "corr-sched-2",
      }).success,
    ).toBe(true);
  });

  it("rejects an action outside the catalogue", () => {
    expect(isAuditAction("user.update")).toBe(true);
    expect(isAuditAction("user.yolo")).toBe(false);
    expect(
      AuditEntrySchema.safeParse({
        actorType: "SYSTEM",
        actorLabel: "system:test",
        action: "user.yolo",
        correlationId: "c",
      }).success,
    ).toBe(false);
  });

  it("represents a non-human actor (FR-013)", () => {
    const parsed = AuditEntrySchema.parse({
      actorType: "AGENT",
      actorId: "018f4a9e-0000-7000-8000-0000000000aa",
      actorLabel: "agent:email-triage",
      action: "agent.run",
      correlationId: "corr-2",
    });
    expect(parsed.actorType).toBe("AGENT");
    expect(parsed.actorId).toBeTruthy();
  });

  it("forces denials to FAILURE with a category-only reason", () => {
    const parsed = DenialEntrySchema.parse({
      actorType: "HUMAN",
      actorLabel: "anonymous",
      action: "auth.denied",
      denialReason: "forbidden",
      correlationId: "corr-3",
    });
    expect(parsed.outcome).toBe("FAILURE");
    expect(parsed.denialReason).toBe("forbidden");

    // Free-text denial reasons would leak which check failed (FR-026).
    expect(
      DenialEntrySchema.safeParse({
        actorType: "HUMAN",
        actorLabel: "anonymous",
        action: "auth.denied",
        denialReason: "user 42 lacks secret:read on secret 'stripe'",
        correlationId: "corr-4",
      }).success,
    ).toBe(false);
  });
});
