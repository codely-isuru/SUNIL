/**
 * In-memory doubles for the runtime's ports.
 *
 * The transaction double has REAL commit/rollback semantics (mutations are staged and only
 * applied on commit), so a test can prove that a failed audit write leaves neither the status
 * change nor the envelope behind — the ADR-005 guarantee, exercised rather than assumed.
 */
import type { Agent, AgentMessage, AuditSpec, Prisma, TransactionClient } from "@sunil/db";
import type { AgentEnvelope, AuditEntry } from "@sunil/core";
import type { AgentMessageStore, AgentStore, AuditedRunner } from "../ports.js";

export function makeAgentRow(overrides: Partial<Agent> = {}): Agent {
  const now = new Date("2026-01-01T00:00:00.000Z");
  return {
    id: "0193f2b0-0000-7000-8000-000000000001",
    slug: "fixture-agent",
    name: "Fixture Agent",
    role: "Runs fixtures",
    systemInstructions: "You are a fixture agent. Answer plainly.",
    toolAllowlist: [],
    providerId: null,
    modelId: "claude-sonnet-4-5",
    maxDurationSeconds: 60,
    tokenBudget: null,
    costBudgetUsd: null,
    heartbeatIntervalSeconds: 30,
    staleThresholdSeconds: 90,
    status: "IDLE",
    currentTaskId: null,
    lastHeartbeatAt: null,
    enabled: true,
    createdAt: now,
    updatedAt: now,
    ...overrides,
  } as Agent;
}

export class FakeAgentStore implements AgentStore {
  readonly rows = new Map<string, Agent>();
  readonly heartbeats: { id: string; at: Date }[] = [];

  constructor(agents: Agent[] = []) {
    for (const agent of agents) this.rows.set(agent.id, agent);
  }

  findById(id: string): Promise<Agent | null> {
    return Promise.resolve(this.rows.get(id) ?? null);
  }

  update(tx: TransactionClient, id: string, data: Prisma.AgentUpdateInput): Promise<Agent> {
    const staged = tx as unknown as StagingTx;
    const current = this.rows.get(id);
    if (!current) return Promise.reject(new Error(`no agent ${id}`));
    const next = { ...current, ...flatten(data) } as Agent;
    staged.stage(() => this.rows.set(id, next));
    return Promise.resolve(next);
  }

  recordHeartbeat(id: string, at: Date): Promise<Agent> {
    const current = this.rows.get(id);
    if (!current) return Promise.reject(new Error(`no agent ${id}`));
    const next = { ...current, lastHeartbeatAt: at } as Agent;
    this.rows.set(id, next);
    this.heartbeats.push({ id, at });
    return Promise.resolve(next);
  }

  findStale(now: Date): Promise<Agent[]> {
    return Promise.resolve(
      [...this.rows.values()].filter(
        (agent) =>
          agent.status === "RUNNING" &&
          agent.lastHeartbeatAt !== null &&
          agent.lastHeartbeatAt.getTime() < now.getTime() - agent.staleThresholdSeconds * 1000,
      ),
    );
  }
}

export class FakeMessageStore implements AgentMessageStore {
  readonly rows: Prisma.AgentMessageCreateInput[] = [];

  append(tx: TransactionClient, data: Prisma.AgentMessageCreateInput): Promise<AgentMessage> {
    const staged = tx as unknown as StagingTx;
    staged.stage(() => this.rows.push(data));
    return Promise.resolve({ id: `msg-${this.rows.length}` } as AgentMessage);
  }

  types(): string[] {
    return this.rows.map((row) => String(row.type));
  }
}

interface StagingTx {
  stage(apply: () => void): void;
}

/**
 * A `UnitOfWork`-shaped runner with real commit/rollback: staged mutations are applied only
 * if the callback AND the audit writes both succeed.
 */
export class FakeAuditedRunner implements AuditedRunner {
  readonly entries: AuditEntry[] = [];
  failAuditWith: Error | undefined;

  async runAudited<T>(spec: AuditSpec<T>, fn: (tx: TransactionClient) => Promise<T>): Promise<T> {
    const staged: (() => void)[] = [];
    const tx = { stage: (apply: () => void) => staged.push(apply) } as unknown as TransactionClient;

    const result = await fn(tx);
    const resolved = typeof spec === "function" ? await spec(result, tx) : spec;
    const entries = Array.isArray(resolved) ? resolved : [resolved as AuditEntry];

    if (this.failAuditWith) throw this.failAuditWith; // nothing is applied — rollback
    this.entries.push(...entries);
    for (const apply of staged) apply();
    return result;
  }
}

/** Non-transactional write target for envelopes emitted outside `runAudited`. */
export const AUTOCOMMIT_TX = {
  stage: (apply: () => void) => apply(),
} as unknown as TransactionClient;

export function envelopeTypes(store: FakeMessageStore): string[] {
  return store.types();
}

export function payloadOf(store: FakeMessageStore, type: AgentEnvelope["type"]): unknown {
  return store.rows.find((row) => row.type === type)?.payload;
}

function flatten(data: Prisma.AgentUpdateInput): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(data)) {
    out[key] = value !== null && typeof value === "object" && "set" in value ? value.set : value;
  }
  return out;
}
