/**
 * Envelope emission (§11.2, FR-071/FR-072).
 *
 * EVERY emission goes through `EnvelopeEmitter.emit`:
 *   validate against the nine-type discriminated union in `@sunil/core`
 *     → reject malformed envelopes BEFORE persistence, logging the failing field
 *     → persist an `agent_messages` row in POSTGRES (never an in-memory buffer)
 *
 * `APPROVAL_REQUIRED` persists and NOTHING ELSE HAPPENS: there is no approval workflow in
 * Phase 1 (FR-071). Do not add one here.
 */
import { ValidationError, parseEnvelope, redact, type AgentEnvelope } from "@sunil/core";
import type { Prisma, TransactionClient } from "@sunil/db";
import type { AgentMessageStore } from "./ports.js";
import { NOOP_AGENT_LOGGER, type AgentLogger } from "./logging.js";

export interface EnvelopeEmitterDeps {
  readonly messages: AgentMessageStore;
  /**
   * Default write target when no transaction is supplied. The guarded client from
   * `@sunil/db` satisfies `TransactionClient` structurally.
   */
  readonly db: TransactionClient;
  readonly logger?: AgentLogger;
}

export class EnvelopeEmitter {
  readonly #messages: AgentMessageStore;
  readonly #db: TransactionClient;
  readonly #logger: AgentLogger;
  #emitted = 0;

  constructor(deps: EnvelopeEmitterDeps) {
    this.#messages = deps.messages;
    this.#db = deps.db;
    this.#logger = deps.logger ?? NOOP_AGENT_LOGGER;
  }

  /** How many envelopes this emitter has persisted — used by run outcomes and tests. */
  get emitted(): number {
    return this.#emitted;
  }

  /**
   * Validate, then persist. Pass `tx` to make the emission part of an audited transaction
   * (the staleness sweep does this, so the status change and its `TASK_FAILED` envelope
   * commit together or not at all).
   */
  async emit(envelope: unknown, tx?: TransactionClient): Promise<AgentEnvelope> {
    const parsed = parseEnvelope(envelope);
    if (!parsed.ok) {
      this.#logger.warn(
        { issues: parsed.issues, type: (envelope as { type?: unknown } | null)?.type ?? null },
        "malformed agent envelope rejected before persistence",
      );
      throw new ValidationError(
        `malformed agent envelope: ${parsed.issues.join("; ")}`,
        parsed.issues.map((issue) => issue.split(":")[0] ?? "<root>"),
      );
    }

    await this.#messages.append(tx ?? this.#db, toCreateInput(parsed.envelope));
    this.#emitted += 1;

    if (parsed.envelope.type === "APPROVAL_REQUIRED") {
      // FR-071: persisted, and that is the whole behaviour in Phase 1.
      this.#logger.info(
        { agentId: parsed.envelope.agentId, taskId: parsed.envelope.taskId },
        "APPROVAL_REQUIRED persisted; no approval workflow exists in Phase 1",
      );
    }

    return parsed.envelope;
  }
}

/**
 * Map a validated envelope onto the `agent_messages` row. The payload is redacted (§9.5)
 * before persist and JSON-normalised so `Date`s become ISO strings.
 */
export function toCreateInput(envelope: AgentEnvelope): Prisma.AgentMessageCreateInput {
  return {
    type: envelope.type,
    agent: { connect: { id: envelope.agentId } },
    taskId: envelope.taskId,
    parentTaskId: envelope.parentTaskId ?? null,
    payload: JSON.parse(JSON.stringify(redact(envelope.payload))) as Prisma.InputJsonValue,
    tokensUsed: envelope.tokensUsed ?? null,
    estimatedCostUsd: envelope.estimatedCostUsd ?? null,
    correlationId: envelope.correlationId,
  };
}
