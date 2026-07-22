/**
 * LLM provider configuration (§5.3, §10.5, FR-012/FR-065).
 *
 * Two hard rules live here:
 *  - `credentialName` is a REFERENCE into the SecretStore. This service will not accept a
 *    credential value, and there is no field on the update shape that could carry one.
 *  - No Phase 1 code path writes `LIVE_VERIFIED`. The enum value exists for Phase 2's live
 *    smoke test; a Phase 1 row can only be `UNCONFIGURED` or `MOCK_VERIFIED` (FR-065), and
 *    the portal renders "unverified against live endpoints" from that field.
 */
import { NotFoundError, ValidationError } from "@sunil/core";
import type { LlmProvider, LlmProviderRepository, SecretRepository } from "@sunil/db";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";

export interface ProviderUpdateInput {
  readonly enabled?: boolean;
  readonly baseUrl?: string | null;
  readonly defaultModel?: string | null;
  /** A SecretStore reference name. Never a value. */
  readonly credentialName?: string | null;
}

export class ProvidersService {
  readonly #providers: LlmProviderRepository;
  readonly #secrets: SecretRepository;
  readonly #uow: AuditedUnitOfWork;

  constructor(
    providers: LlmProviderRepository,
    secrets: SecretRepository,
    uow: AuditedUnitOfWork,
  ) {
    this.#providers = providers;
    this.#secrets = secrets;
    this.#uow = uow;
  }

  list(): Promise<LlmProvider[]> {
    return this.#providers.listAll();
  }

  async update(id: string, input: ProviderUpdateInput): Promise<LlmProvider> {
    const existing = await this.#providers.findById(id);
    if (!existing) throw new NotFoundError("Unknown provider");

    if (input.credentialName) {
      // A dangling reference would fail at call time inside the adapter, where the failure
      // is opaque. Fail here instead, naming the field and not the value.
      const secret = await this.#secrets.findMetadataByName(input.credentialName);
      if (!secret) throw new ValidationError("Unknown secret reference", ["credentialName"]);
    }

    return this.#uow.runAudited(
      (updated: LlmProvider) => ({
        action: "provider.update" as const,
        targetType: "llm_provider",
        targetId: updated.id,
        outcome: "SUCCESS" as const,
        before: {
          enabled: existing.enabled,
          baseUrl: existing.baseUrl,
          defaultModel: existing.defaultModel,
          credentialName: existing.credentialName,
        },
        after: {
          enabled: updated.enabled,
          baseUrl: updated.baseUrl,
          defaultModel: updated.defaultModel,
          credentialName: updated.credentialName,
        },
      }),
      (tx) =>
        this.#providers.update(tx, id, {
          ...(input.enabled === undefined ? {} : { enabled: input.enabled }),
          ...(input.baseUrl === undefined ? {} : { baseUrl: input.baseUrl }),
          ...(input.defaultModel === undefined ? {} : { defaultModel: input.defaultModel }),
          ...(input.credentialName === undefined
            ? {}
            : { credentialName: input.credentialName }),
          // Deliberately absent: verificationStatus. Nothing in Phase 1 sets it (FR-065).
        }),
    );
  }
}
