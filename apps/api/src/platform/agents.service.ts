/**
 * Agent records and the run trigger (§5.6, §11, §13).
 *
 * `apps/api` owns the agent ROW and the enqueue; the runtime lives in `packages/agents` and
 * executes in `apps/worker`. Scope fence (§18.9): no routing, no approvals, no chat — a run
 * is an enqueue and nothing more.
 *
 * `toolAllowlist` must be empty in Phase 1 (FR-070). That is enforced by the Zod schema in
 * `@sunil/core`, not by a check here, so relaxing it in Phase 2 is a reviewed change to the
 * schema rather than a call-site override.
 */
import { NotFoundError, type PageRequest } from "@sunil/core";
import type {
  Agent,
  AgentMessage,
  AgentMessageRepository,
  AgentRepository,
  Prisma,
} from "@sunil/db";
import { randomUUID } from "node:crypto";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import type { QueuePort } from "../jobs/queue.port.js";

export interface AgentCreateInput {
  readonly slug: string;
  readonly name: string;
  readonly role: string;
  readonly systemInstructions: string;
  readonly maxDurationSeconds: number;
  readonly heartbeatIntervalSeconds: number;
  readonly staleThresholdSeconds: number;
  readonly toolAllowlist?: readonly string[];
  readonly providerId?: string | null;
  readonly modelId?: string | null;
  readonly tokenBudget?: number | null;
  readonly costBudgetUsd?: number | null;
  readonly enabled?: boolean;
}

export class AgentsService {
  readonly #agents: AgentRepository;
  readonly #messages: AgentMessageRepository;
  readonly #uow: AuditedUnitOfWork;
  readonly #queue: QueuePort;

  constructor(
    agents: AgentRepository,
    messages: AgentMessageRepository,
    uow: AuditedUnitOfWork,
    queue: QueuePort,
  ) {
    this.#agents = agents;
    this.#messages = messages;
    this.#uow = uow;
    this.#queue = queue;
  }

  list(): Promise<Agent[]> {
    return this.#agents.listAll();
  }

  async get(id: string): Promise<Agent> {
    const agent = await this.#agents.findById(id);
    if (!agent) throw new NotFoundError("Agent not found");
    return agent;
  }

  /** Activity in EMISSION order — the monotonic `sequence`, never `createdAt` (FR-072). */
  async activity(id: string, page: PageRequest): Promise<AgentMessage[]> {
    await this.get(id);
    return this.#messages.listForAgent(id, page);
  }

  create(input: AgentCreateInput): Promise<Agent> {
    const data: Prisma.AgentCreateInput = {
      slug: input.slug,
      name: input.name,
      role: input.role,
      systemInstructions: input.systemInstructions,
      toolAllowlist: (input.toolAllowlist ?? []) as unknown as Prisma.InputJsonValue,
      maxDurationSeconds: input.maxDurationSeconds,
      heartbeatIntervalSeconds: input.heartbeatIntervalSeconds,
      staleThresholdSeconds: input.staleThresholdSeconds,
      ...(input.modelId ? { modelId: input.modelId } : {}),
      ...(input.tokenBudget === undefined || input.tokenBudget === null
        ? {}
        : { tokenBudget: input.tokenBudget }),
      ...(input.costBudgetUsd === undefined || input.costBudgetUsd === null
        ? {}
        : { costBudgetUsd: input.costBudgetUsd }),
      ...(input.enabled === undefined ? {} : { enabled: input.enabled }),
      ...(input.providerId ? { provider: { connect: { id: input.providerId } } } : {}),
    };

    return this.#uow.runAudited(
      (agent: Agent) => ({
        action: "agent.create" as const,
        targetType: "agent",
        targetId: agent.id,
        outcome: "SUCCESS" as const,
        after: { slug: agent.slug, name: agent.name, enabled: agent.enabled },
      }),
      (tx) => this.#agents.create(tx, data),
    );
  }

  async update(id: string, input: Partial<AgentCreateInput>): Promise<Agent> {
    const existing = await this.get(id);
    const data: Prisma.AgentUpdateInput = {
      ...(input.name === undefined ? {} : { name: input.name }),
      ...(input.role === undefined ? {} : { role: input.role }),
      ...(input.systemInstructions === undefined
        ? {}
        : { systemInstructions: input.systemInstructions }),
      ...(input.toolAllowlist === undefined
        ? {}
        : { toolAllowlist: input.toolAllowlist as unknown as Prisma.InputJsonValue }),
      ...(input.maxDurationSeconds === undefined
        ? {}
        : { maxDurationSeconds: input.maxDurationSeconds }),
      ...(input.enabled === undefined ? {} : { enabled: input.enabled }),
    };

    return this.#uow.runAudited(
      (agent: Agent) => ({
        action: "agent.update" as const,
        targetType: "agent",
        targetId: agent.id,
        outcome: "SUCCESS" as const,
        before: { name: existing.name, enabled: existing.enabled },
        after: { name: agent.name, enabled: agent.enabled },
      }),
      (tx) => this.#agents.update(tx, id, data),
    );
  }

  /**
   * Enqueue a skeleton demo run on the `agents` queue. The job id and task id are recorded
   * in the audit entry so the run can be correlated to its `JobExecution` history rows.
   */
  async run(id: string, correlationId: string): Promise<{ taskId: string; jobId: string }> {
    const agent = await this.get(id);
    const taskId = randomUUID();

    return this.#uow.runAudited(
      (result: { taskId: string; jobId: string }) => ({
        action: "agent.run" as const,
        targetType: "agent",
        targetId: agent.id,
        outcome: "SUCCESS" as const,
        after: { taskId: result.taskId, jobId: result.jobId },
      }),
      async () => {
        const { jobId } = await this.#queue.enqueueAgentRun({
          agentId: agent.id,
          taskId,
          correlationId,
        });
        return { taskId, jobId };
      },
    );
  }
}
