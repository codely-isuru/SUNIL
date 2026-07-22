/**
 * The API's wrapper around `UnitOfWork.runAudited` (§9.2 + §9.4).
 *
 * It adds exactly two things and no behaviour:
 *  1. it stamps actor / correlation id / ip / userAgent from the request context, so a call
 *     site cannot forget them and cannot forge them;
 *  2. it increments the request-scoped audit tally, which the global interceptor asserts
 *     before a successful mutating response is allowed out (§9.4).
 *
 * Warning §18.2 still applies underneath: this is the ONLY door to a mutation. There is no
 * ad-hoc `$transaction` anywhere in `apps/api`, and an ESLint fence makes writing one an
 * error rather than a review comment.
 */
import { randomUUID } from "node:crypto";
import type { AuditEntry } from "@sunil/core";
import type { AuditSpec, TransactionClient, UnitOfWork } from "@sunil/db";
import { currentContext, noteAuditWrites } from "../common/request-context.js";

/** What a call site supplies: everything except the fields the context owns. */
export type AuditDraft = Omit<
  AuditEntry,
  "actorType" | "actorId" | "actorLabel" | "correlationId" | "ip" | "userAgent"
> & {
  /** Escape hatch for non-human actors (agent/system emissions) — §5.4, ET-3 3.7. */
  readonly actorOverride?: {
    readonly actorType: AuditEntry["actorType"];
    readonly actorId?: string | null;
    readonly actorLabel: string;
  };
};

export type AuditDraftSpec<T> =
  | AuditDraft
  | readonly AuditDraft[]
  | ((result: T, tx: TransactionClient) => AuditDraft | readonly AuditDraft[] | Promise<AuditDraft | readonly AuditDraft[]>);

export class AuditedUnitOfWork {
  readonly #uow: UnitOfWork;

  constructor(uow: UnitOfWork) {
    this.#uow = uow;
  }

  /** Stamp a draft with the request context. Timestamps stay server-side (FR-050). */
  #stamp(draft: AuditDraft): AuditEntry {
    const context = currentContext();
    const actor = draft.actorOverride ?? {
      actorType: context?.actor.type ?? "SYSTEM",
      actorId: context?.actor.id ?? null,
      actorLabel: context?.actor.label ?? "system:api",
    };
    const { actorOverride: _ignored, ...rest } = draft;
    return {
      ...rest,
      actorType: actor.actorType,
      actorId: actor.actorId ?? null,
      actorLabel: actor.actorLabel,
      correlationId: context?.correlationId ?? `out-of-band-${randomUUID()}`,
      ip: context?.ip ?? null,
      userAgent: context?.userAgent ?? null,
    };
  }

  async runAudited<T>(spec: AuditDraftSpec<T>, fn: (tx: TransactionClient) => Promise<T>): Promise<T> {
    let written = 0;

    const wrapped: AuditSpec<T> = async (result: T, tx: TransactionClient) => {
      const resolved = typeof spec === "function" ? await spec(result, tx) : spec;
      const drafts = Array.isArray(resolved) ? (resolved as readonly AuditDraft[]) : [resolved as AuditDraft];
      written = drafts.length;
      return drafts.map((draft) => this.#stamp(draft));
    };

    const result = await this.#uow.runAudited<T>(wrapped, fn);
    // Only counted AFTER the transaction commits: an entry inside a rolled-back transaction
    // never existed, and must not satisfy the coverage tally.
    noteAuditWrites(written);
    return result;
  }

  /**
   * Record an audit entry for an operation that is not itself a domain mutation — the
   * §8.5 `secret.read` case. It still goes through a transaction because `AuditService` is
   * the only door to `audit_logs` and its `record()` takes a transaction client.
   */
  async recordOutOfBand(draft: AuditDraft): Promise<void> {
    await this.runAudited(draft, async () => undefined);
  }

  /** Read-only transactional work. Named so that using it for a mutation looks wrong. */
  runReadOnly<T>(fn: (tx: TransactionClient) => Promise<T>): Promise<T> {
    return this.#uow.runReadOnly(fn);
  }
}
