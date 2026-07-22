/**
 * Denial records (§9.2, ET-3 3.3).
 *
 * A denied request has no domain mutation to protect, so its single FAILURE record is
 * written outside any transaction. ADR-005's deliberate asymmetry lives inside
 * `AuditService.recordDenial`: if that write fails, the denial still stands and the failure
 * is raised as a `fatal` log — deny-by-default is never weakened to preserve a log line.
 */
import { randomUUID } from "node:crypto";
import type { AuditAction, DenialEntry, DenialReason } from "@sunil/core";
import type { AuditServiceContract } from "@sunil/db";
import { currentContext } from "../common/request-context.js";

export interface DenialDraft {
  readonly action: AuditAction;
  readonly denialReason: DenialReason;
  readonly targetType?: string | null;
  readonly targetId?: string | null;
  readonly after?: unknown;
}

export class DenialRecorder {
  readonly #audit: AuditServiceContract;

  constructor(audit: AuditServiceContract) {
    this.#audit = audit;
  }

  async record(draft: DenialDraft): Promise<void> {
    const context = currentContext();
    const entry: DenialEntry = {
      actorType: context?.actor.type ?? "SYSTEM",
      actorId: context?.actor.id ?? null,
      actorLabel: context?.actor.label ?? "anonymous",
      action: draft.action,
      targetType: draft.targetType ?? null,
      targetId: draft.targetId ?? null,
      after: draft.after ?? null,
      outcome: "FAILURE",
      denialReason: draft.denialReason,
      correlationId: context?.correlationId ?? `out-of-band-${randomUUID()}`,
      ip: context?.ip ?? null,
      userAgent: context?.userAgent ?? null,
    };
    await this.#audit.recordDenial(entry);
    if (context) context.denialAudited = true;
  }
}
