/**
 * Thin repositories for settings, providers, secrets, agents, usage and job history.
 * Same contract as the identity repositories: one query each, writes take a
 * `TransactionClient` so they land inside a `UnitOfWork.runAudited` call.
 */
import type {
  Agent,
  AgentMessage,
  JobExecution,
  JobOutcome,
  LlmProvider,
  Prisma,
  Secret,
  SystemSetting,
  UsageRecord,
} from "@prisma/client";
import type { PageRequest, Paged } from "@sunil/core";
import type { SunilPrismaClient, TransactionClient } from "../client.js";

/** Every model in the §5.3/§5.5/§5.6/§5.7 groups — see the note in `identity.ts`. */
export type { Agent, AgentMessage, JobExecution, LlmProvider, Secret, SystemSetting, UsageRecord };

/**
 * Postgres foreign-key violation, surfaced by Prisma as error code P2003.
 *
 * Matched structurally rather than with `instanceof Prisma.PrismaClientKnownRequestError`
 * so this module keeps its type-only import of `@prisma/client` and pulls no generated
 * runtime code into the repository layer.
 */
function isForeignKeyViolation(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    (error as { code?: unknown }).code === "P2003"
  );
}

/** Everything an API may return about a secret (§8.4 DTO allowlist). */
export const SECRET_METADATA_SELECT = {
  id: true,
  name: true,
  description: true,
  fingerprint: true,
  version: true,
  masterKeyVersion: true,
  rotatedAt: true,
  createdAt: true,
  updatedAt: true,
} as const satisfies Prisma.SecretSelect;

export class SecretRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  /** Full row INCLUDING ciphertext — server-side decryption path only. */
  findByNameWithCiphertext(name: string): Promise<Secret | null> {
    return this.#prisma.secret.findUnique({ where: { name } });
  }

  /** Metadata projection. This is what any read path that faces a caller must use. */
  findMetadataByName(name: string) {
    return this.#prisma.secret.findUnique({ where: { name }, select: SECRET_METADATA_SELECT });
  }

  listMetadata() {
    return this.#prisma.secret.findMany({
      select: SECRET_METADATA_SELECT,
      orderBy: { name: "asc" },
    });
  }

  create(tx: TransactionClient, data: Prisma.SecretCreateInput): Promise<Secret> {
    return tx.secret.create({ data });
  }

  update(tx: TransactionClient, name: string, data: Prisma.SecretUpdateInput): Promise<Secret> {
    return tx.secret.update({ where: { name }, data });
  }

  delete(tx: TransactionClient, name: string): Promise<Secret> {
    return tx.secret.delete({ where: { name } });
  }

  /** A secret referenced by a provider or an MFA credential may not be deleted (§13). */
  async countReferences(name: string): Promise<number> {
    const [providers, mfa] = await Promise.all([
      this.#prisma.llmProvider.count({ where: { credentialName: name } }),
      this.#prisma.mfaCredential.count({ where: { secretName: name } }),
    ]);
    return providers + mfa;
  }
}

export class SystemSettingRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  listAll(): Promise<SystemSetting[]> {
    return this.#prisma.systemSetting.findMany({ orderBy: { key: "asc" } });
  }

  findByKey(key: string): Promise<SystemSetting | null> {
    return this.#prisma.systemSetting.findUnique({ where: { key } });
  }

  upsert(
    tx: TransactionClient,
    key: string,
    value: Prisma.InputJsonValue,
    updatedById: string | null,
  ): Promise<SystemSetting> {
    return tx.systemSetting.update({ where: { key }, data: { value, updatedById } });
  }
}

export class LlmProviderRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  listAll(): Promise<LlmProvider[]> {
    return this.#prisma.llmProvider.findMany({ orderBy: { slug: "asc" } });
  }

  findBySlug(slug: string): Promise<LlmProvider | null> {
    return this.#prisma.llmProvider.findUnique({ where: { slug } });
  }

  findById(id: string): Promise<LlmProvider | null> {
    return this.#prisma.llmProvider.findUnique({ where: { id } });
  }

  /**
   * NOTE: nothing in Phase 1 may set `verificationStatus` to `LIVE_VERIFIED` (FR-065).
   * The enum value exists only for Phase 2's live smoke test.
   */
  update(
    tx: TransactionClient,
    id: string,
    data: Prisma.LlmProviderUpdateInput,
  ): Promise<LlmProvider> {
    return tx.llmProvider.update({ where: { id }, data });
  }
}

export class AgentRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  listAll(): Promise<Agent[]> {
    return this.#prisma.agent.findMany({ orderBy: { slug: "asc" } });
  }

  findById(id: string): Promise<Agent | null> {
    return this.#prisma.agent.findUnique({ where: { id } });
  }

  findBySlug(slug: string): Promise<Agent | null> {
    return this.#prisma.agent.findUnique({ where: { slug } });
  }

  create(tx: TransactionClient, data: Prisma.AgentCreateInput): Promise<Agent> {
    return tx.agent.create({ data });
  }

  update(tx: TransactionClient, id: string, data: Prisma.AgentUpdateInput): Promise<Agent> {
    return tx.agent.update({ where: { id }, data });
  }

  /**
   * Heartbeat bookkeeping from inside a running job (§11.3). Not a security mutation and
   * deliberately not audited — the STALE transition that follows from it is.
   */
  recordHeartbeat(id: string, at: Date): Promise<Agent> {
    return this.#prisma.agent.update({ where: { id }, data: { lastHeartbeatAt: at } });
  }

  /**
   * Out-of-process staleness detection (§11.3): RUNNING agents whose last heartbeat is older
   * than their own per-agent threshold.
   *
   * The threshold is a COLUMN, so the comparison is applied in memory after an indexed fetch
   * of running agents rather than in raw SQL — ADR-004 confines raw SQL to migration files.
   * The candidate set is bounded by the number of concurrently running agents.
   */
  async findStale(now: Date): Promise<Agent[]> {
    const running = await this.#prisma.agent.findMany({
      where: { status: "RUNNING", lastHeartbeatAt: { not: null } },
    });
    return running.filter(
      (agent) =>
        agent.lastHeartbeatAt !== null &&
        agent.lastHeartbeatAt.getTime() < now.getTime() - agent.staleThresholdSeconds * 1000,
    );
  }
}

export class AgentMessageRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  /**
   * Envelopes are validated against the Zod discriminated union in `@sunil/core` BEFORE they
   * reach here (§11.2). This repository does not re-validate; it persists.
   */
  append(
    tx: TransactionClient,
    data: Prisma.AgentMessageCreateInput,
  ): Promise<AgentMessage> {
    return tx.agentMessage.create({ data });
  }

  /** Activity in emission order (FR-072): the monotonic `sequence`, never `createdAt`. */
  listForTask(agentId: string, taskId: string): Promise<AgentMessage[]> {
    return this.#prisma.agentMessage.findMany({
      where: { agentId, taskId },
      orderBy: { sequence: "asc" },
    });
  }

  listForAgent(agentId: string, page: PageRequest): Promise<AgentMessage[]> {
    return this.#prisma.agentMessage.findMany({
      where: { agentId },
      orderBy: { sequence: "asc" },
      skip: (page.page - 1) * page.pageSize,
      take: page.pageSize,
    });
  }
}

export class UsageRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  /**
   * Usage rows are written per LLM call, success or failure. They are NOT security
   * mutations, so they are written outside the audited transaction — and they never carry
   * prompt or completion text (FR-064).
   */
  record(data: Prisma.UsageRecordCreateInput): Promise<UsageRecord> {
    return this.#prisma.usageRecord.create({ data });
  }

  /**
   * Scalar path: `agentId` is set directly instead of through `agent: { connect: { id } }`.
   *
   * The checked input forces a relation connect, which is the wrong shape for a column the
   * schema declares nullable — expressing "no agent" means omitting a nested writer rather
   * than writing `agentId: null`, and a stale id fails with a Prisma "record to connect not
   * found" rather than anything the caller can reason about.
   *
   * NOTE what this does NOT do: it does not let a usage row reference an agent that does not
   * exist. `usage_records.agent_id` is a real foreign key, so a dangling id fails with
   * P2003 here exactly as it did before. Use `recordAllowingMissingAgent` when the agent may
   * have vanished mid-call and the usage row still has to be written.
   */
  recordUnchecked(data: Prisma.UsageRecordUncheckedCreateInput): Promise<UsageRecord> {
    return this.#prisma.usageRecord.create({ data });
  }

  /**
   * Write the usage row even if the referenced agent no longer exists, by degrading
   * `agentId` to null.
   *
   * FR-064 requires one usage row per LLM call, success or failure. An agent deleted while
   * one of its calls is in flight must not cost us the row — losing the accounting record is
   * strictly worse than losing the attribution, and `usage_records.agentId` is nullable
   * precisely so the row can stand alone.
   *
   * Implemented as insert-then-degrade rather than a pre-flight existence check, because a
   * check would be a race: the agent can be deleted between the check and the insert.
   */
  async recordAllowingMissingAgent(
    data: Prisma.UsageRecordUncheckedCreateInput,
  ): Promise<UsageRecord> {
    try {
      return await this.#prisma.usageRecord.create({ data });
    } catch (error) {
      if (data.agentId == null || !isForeignKeyViolation(error)) throw error;
      return this.#prisma.usageRecord.create({ data: { ...data, agentId: null } });
    }
  }

  async listPaged(page: PageRequest): Promise<Paged<UsageRecord>> {
    const skip = (page.page - 1) * page.pageSize;
    const [items, total] = await Promise.all([
      this.#prisma.usageRecord.findMany({
        orderBy: { createdAt: "desc" },
        skip,
        take: page.pageSize,
      }),
      this.#prisma.usageRecord.count(),
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

/**
 * Narrowing for `JobExecutionRepository.listPaged`. `queue` is typed `string` rather than
 * `QueueName` because the column is a plain string and history predating a queue rename must
 * stay queryable.
 */
export interface JobExecutionFilter {
  readonly queue?: string;
  readonly outcome?: JobOutcome;
  readonly jobName?: string;
  readonly schedulerId?: string;
  readonly startedFrom?: Date;
  readonly startedTo?: Date;
}

export class JobExecutionRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  /** History lives in Postgres so it survives a Redis wipe (FR-083, ET-4 4.8). */
  start(data: Prisma.JobExecutionCreateInput): Promise<JobExecution> {
    return this.#prisma.jobExecution.create({ data });
  }

  finish(
    id: string,
    data: Pick<Prisma.JobExecutionUpdateInput, "outcome" | "finishedAt" | "durationMs" | "error" | "result">,
  ): Promise<JobExecution> {
    return this.#prisma.jobExecution.update({ where: { id }, data });
  }

  findByBullJobId(bullJobId: string): Promise<JobExecution[]> {
    return this.#prisma.jobExecution.findMany({ where: { bullJobId } });
  }

  /**
   * Executions still marked RUNNING whose `startedAt` predates `cutoff` — i.e. orphans left
   * behind when a worker died mid-job, since nothing ever wrote their terminal row.
   *
   * Intended for the worker's boot reconciliation. This is a QUERY ONLY: transitioning an
   * orphan to `STALLED` is a security-relevant mutation and belongs in a
   * `UnitOfWork.runAudited` call owned by the caller, not in a repository.
   *
   * `cutoff` is an absolute instant supplied by the caller rather than a duration resolved
   * here, so the caller's clock is the only clock involved and the boundary is testable.
   */
  findRunningStartedBefore(cutoff: Date, limit = 500): Promise<JobExecution[]> {
    return this.#prisma.jobExecution.findMany({
      where: { outcome: "RUNNING", startedAt: { lt: cutoff } },
      orderBy: { startedAt: "asc" },
      take: limit,
    });
  }

  /**
   * Paged history, optionally narrowed. `GET /api/jobs/history` (FR-085) filters by queue
   * and outcome; `jobName` and `schedulerId` are included because ET-4's assertions are
   * stated per scheduler definition and need to be directly queryable (ADR-010).
   *
   * The filter is an optional second argument, so every existing `listPaged(page)` call is
   * unaffected.
   */
  async listPaged(
    page: PageRequest,
    filter: JobExecutionFilter = {},
  ): Promise<Paged<JobExecution>> {
    const where: Prisma.JobExecutionWhereInput = {};
    if (filter.queue !== undefined) where.queue = filter.queue;
    if (filter.outcome !== undefined) where.outcome = filter.outcome;
    if (filter.jobName !== undefined) where.jobName = filter.jobName;
    if (filter.schedulerId !== undefined) where.schedulerId = filter.schedulerId;
    if (filter.startedFrom !== undefined || filter.startedTo !== undefined) {
      where.startedAt = {
        ...(filter.startedFrom !== undefined ? { gte: filter.startedFrom } : {}),
        ...(filter.startedTo !== undefined ? { lte: filter.startedTo } : {}),
      };
    }

    const skip = (page.page - 1) * page.pageSize;
    const [items, total] = await Promise.all([
      this.#prisma.jobExecution.findMany({
        where,
        orderBy: { startedAt: "desc" },
        skip,
        take: page.pageSize,
      }),
      this.#prisma.jobExecution.count({ where }),
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
