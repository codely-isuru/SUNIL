/**
 * Integration proofs that need a REAL Postgres, for the claims that are only meaningful
 * against one: FR-072 (envelopes are in Postgres, not memory), FR-073 (a silent agent is
 * detectable as failed, audited), §6.2 (the session sweep).
 *
 * Skipped unless `SUNIL_TEST_DATABASE_URL` points at a database with the initial migration
 * applied, so `pnpm test` stays green on a machine with no containers (FR-003).
 *
 * Run locally:
 *   docker run -d --name sunil-t4-postgres -p 55434:5432 -e POSTGRES_HOST_AUTH_METHOD=trust \
 *     -e POSTGRES_DB=sunil_t4 pgvector/pgvector:0.8.5-pg16
 *   DATABASE_URL=postgresql://postgres@127.0.0.1:55434/sunil_t4 \
 *     pnpm --filter @sunil/db exec prisma migrate deploy
 *   SUNIL_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55434/sunil_t4 \
 *     pnpm --filter @sunil/worker test
 */
import { createHash, randomUUID } from "node:crypto";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  AgentMessageRepository,
  AgentRepository,
  AuditService,
  SessionRepository,
  UnitOfWork,
  createPrismaClient,
} from "@sunil/db";
import { AgentRuntime, StaleAgentSweeper } from "@sunil/agents";
import { createLogger } from "../logger.js";
import { runAgentJob } from "../processors/agents.js";
import { runAgentStalenessSweep, runSessionSweep } from "../processors/system.js";

const DSN = process.env["SUNIL_TEST_DATABASE_URL"];
const describeDb = DSN ? describe : describe.skip;

describeDb("worker processors against real Postgres", () => {
  const prisma = createPrismaClient(DSN ? { datasourceUrl: DSN } : {});
  const audit = new AuditService(prisma);
  const uow = new UnitOfWork(prisma, audit);
  const agents = new AgentRepository(prisma);
  const messages = new AgentMessageRepository(prisma);
  const sessions = new SessionRepository(prisma);
  const logger = createLogger("worker-integration", "silent");
  const runtime = new AgentRuntime({ agents, messages, uow, db: prisma });

  const suffix = randomUUID().slice(0, 8);
  let agentId = "";

  beforeAll(async () => {
    const created = await uow.runAudited(
      {
        actorType: "SYSTEM",
        actorId: null,
        actorLabel: "integration-test",
        action: "agent.create",
        targetType: "agent",
        correlationId: `test-${suffix}`,
      },
      (tx) =>
        agents.create(tx, {
          slug: `t4-fixture-${suffix}`,
          name: "T4 Fixture",
          role: "integration fixture",
          systemInstructions: "You are a fixture agent.",
          maxDurationSeconds: 60,
          heartbeatIntervalSeconds: 30,
          staleThresholdSeconds: 90,
        }),
    );
    agentId = created.id;
  });

  afterAll(async () => {
    await prisma.$disconnect();
  });

  it("runs an agent job and persists every envelope in emission order (FR-072)", async () => {
    const correlationId = `corr-agent-${suffix}`;
    const outcome = await runAgentJob({ runtime, agents, logger }, {
      agentId,
      objective: "prove the runtime persists activity",
      assignedBy: "integration-test",
      correlationId,
    });

    expect(outcome.status).toBe("COMPLETED");

    // A SECOND client, as a process restart would use: the record is in Postgres, not memory.
    const reader = createPrismaClient(DSN ? { datasourceUrl: DSN } : {});
    try {
      const rows = await reader.agentMessage.findMany({
        where: { agentId, taskId: outcome.taskId },
        orderBy: { sequence: "asc" },
      });
      expect(rows.map((row) => row.type)).toEqual([
        "TASK_ASSIGNED",
        "TASK_STARTED",
        "TASK_PROGRESS",
        "TASK_COMPLETED",
      ]);
      expect(rows.every((row) => row.correlationId === correlationId)).toBe(true);
      // Monotonic emission order, from the sequence column rather than createdAt.
      const sequences = rows.map((row) => row.sequence);
      expect([...sequences].sort((a, b) => Number(a - b))).toEqual(sequences);
    } finally {
      await reader.$disconnect();
    }

    const agent = await agents.findById(agentId);
    expect(agent?.status).toBe("IDLE");
    expect(agent?.currentTaskId).toBeNull();
  });

  it("audits the run start and finish", async () => {
    const rows = await prisma.auditLog.findMany({
      where: { action: "agent.run", targetId: agentId },
      orderBy: { createdAt: "asc" },
    });
    expect(rows.length).toBeGreaterThanOrEqual(2);
    expect(rows[0]?.actorType).toBe("AGENT");
  });

  it("marks a silent agent FAILED, emits TASK_FAILED and audits it (FR-073)", async () => {
    const taskId = randomUUID();
    await uow.runAudited(
      {
        actorType: "SYSTEM",
        actorId: null,
        actorLabel: "integration-test",
        action: "agent.update",
        targetType: "agent",
        targetId: agentId,
        correlationId: `test-stale-${suffix}`,
      },
      (tx) =>
        agents.update(tx, agentId, {
          status: "RUNNING",
          currentTaskId: taskId,
          // Silent for far longer than staleThresholdSeconds.
          lastHeartbeatAt: new Date(Date.now() - 10 * 60_000),
        }),
    );

    const sweeper = new StaleAgentSweeper({ agents, emitter: runtime.emitter, uow });
    const result = await runAgentStalenessSweep({ sweeper, logger }, `corr-stale-${suffix}`);

    expect(result.agentIds).toContain(agentId);
    const agent = await agents.findById(agentId);
    expect(agent?.status).toBe("FAILED");
    expect(agent?.currentTaskId).toBeNull();

    const failures = await prisma.agentMessage.findMany({ where: { agentId, taskId } });
    expect(failures.map((row) => row.type)).toEqual(["TASK_FAILED"]);

    const auditRows = await prisma.auditLog.findMany({
      where: { action: "agent.stale", targetId: agentId },
    });
    expect(auditRows).toHaveLength(1);
    expect(auditRows[0]?.outcome).toBe("FAILURE");
    expect(auditRows[0]?.actorType).toBe("SYSTEM");
  });

  it("revokes expired sessions and audits the sweep, and is a no-op when nothing is due", async () => {
    const user = await uow.runAudited(
      {
        actorType: "SYSTEM",
        actorId: null,
        actorLabel: "integration-test",
        action: "user.create",
        targetType: "user",
        correlationId: `test-user-${suffix}`,
      },
      (tx) =>
        tx.user.create({
          data: {
            email: `t4-${suffix}@example.test`,
            passwordHash: "$argon2id$v=19$m=1,t=1,p=1$fixture$fixture",
            displayName: "T4 Fixture User",
          },
        }),
    );

    const past = new Date(Date.now() - 60 * 60_000);
    await uow.runAudited(
      {
        actorType: "SYSTEM",
        actorId: null,
        actorLabel: "integration-test",
        action: "auth.login.success",
        targetType: "session",
        correlationId: `test-session-${suffix}`,
      },
      (tx) =>
        sessions.create(tx, {
          tokenHash: createHash("sha256").update(`t4-${suffix}`).digest("hex"),
          user: { connect: { id: user.id } },
          state: "ACTIVE",
          csrfSecret: "fixture-csrf-secret",
          idleExpiresAt: past,
          absoluteExpiresAt: past,
        }),
    );

    const swept = await runSessionSweep({ prisma, sessions, uow, logger }, `corr-sweep-${suffix}`);
    expect(swept.revoked).toBeGreaterThanOrEqual(1);

    const rows = await sessions.listForUser(user.id);
    expect(rows[0]?.state).toBe("REVOKED");
    expect(rows[0]?.revokedReason).toBe("expired_sweep");

    const auditRows = await prisma.auditLog.findMany({
      where: { action: "auth.session.revoke", correlationId: `corr-sweep-${suffix}` },
    });
    expect(auditRows).toHaveLength(1);

    // Second run: nothing due, so no mutation and no audit noise.
    const again = await runSessionSweep({ prisma, sessions, uow, logger }, `corr-sweep2-${suffix}`);
    expect(again.revoked).toBe(0);
    expect(
      await prisma.auditLog.count({ where: { correlationId: `corr-sweep2-${suffix}` } }),
    ).toBe(0);
  });
});
