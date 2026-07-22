/**
 * Integration proofs that need a REAL Postgres.
 *
 * Skipped unless `SUNIL_TEST_DATABASE_URL` points at a database with the initial migration
 * applied, so `pnpm test` stays green on a machine with no containers running (FR-003).
 * The Phase 1 acceptance run sets it.
 *
 * Run locally:
 *   docker run -d --name sunil-pg -e POSTGRES_PASSWORD=... -p 55432:5432 pgvector/pgvector:pg16
 *   DATABASE_URL=... pnpm --filter @sunil/db exec prisma migrate deploy
 *   SUNIL_TEST_DATABASE_URL=$DATABASE_URL pnpm --filter @sunil/db test
 */
import { randomUUID } from "node:crypto";
import { afterAll, describe, expect, it } from "vitest";
import { AuditWriteFailedError, OWNER_ROLE_ID, PERMISSIONS, SEED_ROLES } from "@sunil/core";
import { AuditService, type AuditServiceContract } from "../audit/audit-service.js";
import { AuditAppendOnlyError, createPrismaClient } from "../client.js";
import { UnitOfWork } from "../unit-of-work.js";
import { hashPassword } from "../password.js";
import { JobExecutionRepository, UsageRepository } from "../repositories/platform.js";

const DSN = process.env["SUNIL_TEST_DATABASE_URL"];
const describeDb = DSN ? describe : describe.skip;

describeDb("schema + migration against real Postgres", () => {
  const prisma = createPrismaClient(DSN ? { datasourceUrl: DSN } : {});
  const audit = new AuditService(prisma);
  const uow = new UnitOfWork(prisma, audit);

  afterAll(async () => {
    await prisma.$disconnect();
  });

  it("has the pgvector extension installed by migration (FR-010)", async () => {
    const rows = await prisma.$queryRaw<{ extname: string }[]>`
      SELECT extname FROM pg_extension
    `;
    expect(rows.map((r) => r.extname)).toContain("vector");
  });

  it("carries no vector column anywhere — installation only (A-05)", async () => {
    const rows = await prisma.$queryRaw<{ count: bigint }[]>`
      SELECT count(*)::bigint AS count
      FROM information_schema.columns
      WHERE table_schema = 'public' AND udt_name = 'vector'
    `;
    expect(Number(rows[0]?.count ?? 0)).toBe(0);
  });

  it("seeded all four system roles with their fixed UUIDs", async () => {
    const roles = await prisma.role.findMany({ orderBy: { slug: "asc" } });
    expect(roles.map((r) => r.slug).sort()).toEqual(["admin", "agent", "owner", "viewer"]);
    for (const seed of SEED_ROLES) {
      expect(roles.find((r) => r.slug === seed.slug)?.id).toBe(seed.id);
    }
  });

  it("seeded all 21 permissions and granted every one of them to the owner", async () => {
    const permissions = await prisma.permission.findMany();
    expect(permissions).toHaveLength(PERMISSIONS.length);

    const ownerGrants = await prisma.rolePermission.findMany({
      where: { roleId: OWNER_ROLE_ID },
      select: { permission: { select: { key: true } } },
    });
    expect(ownerGrants.map((g) => g.permission.key).sort()).toEqual([...PERMISSIONS].sort());
  });

  it("holds exactly one owner", async () => {
    expect(await prisma.userRole.count({ where: { roleId: OWNER_ROLE_ID } })).toBe(1);
  });

  it("REJECTS a second owner at the database (ADR-001 layer c)", async () => {
    const email = `second-owner-${randomUUID()}@example.test`;
    const user = await prisma.user.create({
      data: {
        email,
        passwordHash: await hashPassword(`throwaway-${randomUUID()}`),
        displayName: "Second owner attempt",
      },
    });

    await expect(
      prisma.userRole.create({ data: { userId: user.id, roleId: OWNER_ROLE_ID } }),
    ).rejects.toThrow();

    await prisma.user.delete({ where: { id: user.id } });
  });

  it("REJECTS an UPDATE of an audit row even through raw SQL (§9.3 layer 2)", async () => {
    const correlationId = `it-${randomUUID()}`;
    await prisma.auditLog.create({
      data: {
        actorType: "SYSTEM",
        actorLabel: "system:test",
        action: "system.bootstrap",
        outcome: "SUCCESS",
        correlationId,
      },
    });

    await expect(
      prisma.$executeRaw`UPDATE audit_logs SET action = 'tampered' WHERE correlation_id = ${correlationId}`,
    ).rejects.toThrow(/append-only/i);

    await expect(
      prisma.$executeRaw`DELETE FROM audit_logs WHERE correlation_id = ${correlationId}`,
    ).rejects.toThrow(/append-only/i);
  });

  it("REJECTS an update through the guarded client too (§9.3 layer 1)", async () => {
    await expect(
      prisma.auditLog.updateMany({ where: {}, data: { action: "tampered" } }),
    ).rejects.toBeInstanceOf(AuditAppendOnlyError);
  });

  it("ROLLS BACK a real mutation when the audit insert fails (Gate 1)", async () => {
    const email = `rollback-${randomUUID()}@example.test`;
    const exploding: AuditServiceContract = {
      record: () => Promise.reject(new Error("audit store unavailable")),
      recordDenial: () => Promise.resolve(),
      query: () => Promise.reject(new Error("not used")),
    };
    const failingUow = new UnitOfWork(prisma, exploding);

    await expect(
      failingUow.runAudited(
        {
          actorType: "SYSTEM",
          actorLabel: "system:test",
          action: "user.create",
          outcome: "SUCCESS",
          correlationId: `rollback-${randomUUID()}`,
        },
        async (tx) => {
          await tx.user.create({
            data: {
              email,
              passwordHash: await hashPassword(`throwaway-${randomUUID()}`),
              displayName: "Rollback probe",
            },
          });
        },
      ),
    ).rejects.toBeInstanceOf(AuditWriteFailedError);

    // Postgres rolled the transaction back: the user does not exist.
    expect(await prisma.user.findUnique({ where: { email } })).toBeNull();
  });

  it("commits mutation and audit record together on the happy path", async () => {
    const email = `commit-${randomUUID()}@example.test`;
    const correlationId = `commit-${randomUUID()}`;

    const created = await uow.runAudited(
      {
        actorType: "SYSTEM",
        actorLabel: "system:test",
        action: "user.create",
        targetType: "user",
        outcome: "SUCCESS",
        correlationId,
      },
      async (tx) =>
        tx.user.create({
          data: {
            email,
            passwordHash: await hashPassword(`throwaway-${randomUUID()}`),
            displayName: "Commit probe",
          },
        }),
    );

    expect(await prisma.user.findUnique({ where: { email } })).not.toBeNull();
    expect(await prisma.auditLog.count({ where: { correlationId } })).toBe(1);

    await prisma.user.delete({ where: { id: created.id } });
  });

  it("stores the audit timestamp server-side (FR-050)", async () => {
    const correlationId = `ts-${randomUUID()}`;
    const before = new Date(Date.now() - 5_000);
    await prisma.auditLog.create({
      data: {
        actorType: "SYSTEM",
        actorLabel: "system:test",
        action: "system.bootstrap",
        outcome: "SUCCESS",
        correlationId,
      },
    });
    const row = await prisma.auditLog.findFirst({ where: { correlationId } });
    expect(row?.createdAt.getTime()).toBeGreaterThan(before.getTime());
  });

  it("uses UUIDv7 primary keys (FR-015)", async () => {
    const row = await prisma.auditLog.findFirst({ orderBy: { createdAt: "desc" } });
    expect(row?.id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  });

  /**
   * Every assertion below is scoped to a marker minted fresh for THIS run and asserted as an
   * exact set, never as "at least one". A suite that counts rows globally passes for the
   * wrong reason the moment a previous run leaves data behind. Rows are also created on both
   * sides of every boundary, so the test fails if the predicate stops discriminating.
   */
  describe("JobExecutionRepository.findRunningStartedBefore (orphan reconciliation)", () => {
    it("returns exactly the RUNNING rows strictly older than the cutoff", async () => {
      const repo = new JobExecutionRepository(prisma);
      const runTag = `it-orphan-${randomUUID()}`;
      const cutoff = new Date("2026-07-21T12:00:00.000Z");
      const older = new Date(cutoff.getTime() - 60_000);
      const newer = new Date(cutoff.getTime() + 60_000);

      const row = (outcome: "RUNNING" | "COMPLETED", startedAt: Date, label: string) => ({
        jobName: runTag,
        queue: "system",
        bullJobId: `${runTag}:${label}`,
        attempt: 1,
        startedAt,
        outcome,
      });

      const orphan = await prisma.jobExecution.create({ data: row("RUNNING", older, "orphan") });
      const tooNew = await prisma.jobExecution.create({ data: row("RUNNING", newer, "too-new") });
      const finished = await prisma.jobExecution.create({
        data: row("COMPLETED", older, "finished"),
      });
      // `lt`, not `lte`: a row started exactly at the cutoff is not yet an orphan.
      const onBoundary = await prisma.jobExecution.create({
        data: row("RUNNING", cutoff, "boundary"),
      });

      try {
        const found = await repo.findRunningStartedBefore(cutoff, 1000);
        const mine = found.filter((r) => r.jobName === runTag).map((r) => r.id);

        expect(mine).toEqual([orphan.id]);
        expect(mine).not.toContain(tooNew.id);
        expect(mine).not.toContain(finished.id);
        expect(mine).not.toContain(onBoundary.id);

        // Negative control: move the cutoff before the orphan and the result must empty out.
        // Without this, the tag filter alone could be carrying the assertion above.
        const earlier = await repo.findRunningStartedBefore(new Date(older.getTime() - 1), 1000);
        expect(earlier.filter((r) => r.jobName === runTag)).toEqual([]);
      } finally {
        await prisma.jobExecution.deleteMany({ where: { jobName: runTag } });
      }
    });
  });

  describe("JobExecutionRepository.listPaged filtering (FR-085)", () => {
    it("narrows by queue and outcome without over- or under-counting", async () => {
      const repo = new JobExecutionRepository(prisma);
      const runTag = `it-filter-${randomUUID()}`;
      const startedAt = new Date();

      await prisma.jobExecution.createMany({
        data: [
          { jobName: runTag, queue: "system", bullJobId: `${runTag}:1`, attempt: 1, startedAt, outcome: "COMPLETED" },
          { jobName: runTag, queue: "system", bullJobId: `${runTag}:2`, attempt: 1, startedAt, outcome: "FAILED" },
          { jobName: runTag, queue: "agents", bullJobId: `${runTag}:3`, attempt: 1, startedAt, outcome: "FAILED" },
        ],
      });

      try {
        const page = { page: 1, pageSize: 50 };
        const all = await repo.listPaged(page, { jobName: runTag });
        const systemQueue = await repo.listPaged(page, { jobName: runTag, queue: "system" });
        const failed = await repo.listPaged(page, { jobName: runTag, outcome: "FAILED" });
        const systemFailed = await repo.listPaged(page, {
          jobName: runTag,
          queue: "system",
          outcome: "FAILED",
        });

        expect(all.total).toBe(3);
        expect(systemQueue.total).toBe(2);
        expect(failed.total).toBe(2);
        expect(systemFailed.total).toBe(1);
        expect(systemFailed.items).toHaveLength(1);
        expect(systemFailed.items[0]?.bullJobId).toBe(`${runTag}:2`);
        // `total` comes from the same filter as `items`, so `hasMore` is truthful.
        expect(systemFailed.hasMore).toBe(false);
      } finally {
        await prisma.jobExecution.deleteMany({ where: { jobName: runTag } });
      }
    });
  });

  describe("UsageRepository write paths against the real foreign key", () => {
    it("rejects a dangling agentId on the plain scalar path", async () => {
      const repo = new UsageRepository(prisma);
      const missingAgentId = randomUUID();

      await expect(
        repo.recordUnchecked({
          provider: "anthropic",
          model: "m",
          feature: `it-${missingAgentId}`,
          agentId: missingAgentId,
          tokensIn: 1,
          tokensOut: 1,
          latencyMs: 1,
        }),
      ).rejects.toThrow();
    });

    it("still writes the usage row when the agent has vanished, with attribution dropped", async () => {
      const repo = new UsageRepository(prisma);
      const feature = `it-usage-${randomUUID()}`;

      const written = await repo.recordAllowingMissingAgent({
        provider: "anthropic",
        model: "m",
        feature,
        agentId: randomUUID(),
        tokensIn: 11,
        tokensOut: 22,
        latencyMs: 33,
      });

      try {
        expect(written.agentId).toBeNull();
        // FR-064's accounting row survives; only the agent attribution is lost.
        expect(written.tokensIn).toBe(11);
        expect(await prisma.usageRecord.count({ where: { feature } })).toBe(1);
      } finally {
        await prisma.usageRecord.deleteMany({ where: { feature } });
      }
    });

    it("preserves attribution when the agent DOES exist", async () => {
      const repo = new UsageRepository(prisma);
      const feature = `it-usage-${randomUUID()}`;
      const agent = await prisma.agent.create({
        data: {
          slug: `it-agent-${randomUUID()}`,
          name: "Integration probe",
          role: "probe",
          systemInstructions: "probe",
          maxDurationSeconds: 60,
        },
      });

      try {
        const written = await repo.recordAllowingMissingAgent({
          provider: "anthropic",
          model: "m",
          feature,
          agentId: agent.id,
          tokensIn: 1,
          tokensOut: 1,
          latencyMs: 1,
        });
        expect(written.agentId).toBe(agent.id);

        // onDelete: Restrict — the agent cannot be removed while a usage row references it.
        await expect(prisma.agent.delete({ where: { id: agent.id } })).rejects.toThrow();
      } finally {
        await prisma.usageRecord.deleteMany({ where: { feature } });
        await prisma.agent.delete({ where: { id: agent.id } });
      }
    });
  });

  it("keeps agent message emission order monotonic (FR-072)", async () => {
    const rows = await prisma.$queryRaw<{ column_default: string | null }[]>`
      SELECT column_default FROM information_schema.columns
      WHERE table_name = 'agent_messages' AND column_name = 'sequence'
    `;
    expect(rows[0]?.column_default ?? "").toContain("nextval");
  });
});
