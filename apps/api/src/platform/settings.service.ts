/**
 * System settings (§5.3, §13). Values are JSON; the row's `valueType` drives portal
 * rendering. Updates are audited with before/after, redacted by the audit service.
 */
import { NotFoundError, type JsonValue } from "@sunil/core";
import type { SystemSetting, SystemSettingRepository } from "@sunil/db";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";

export class SettingsService {
  readonly #settings: SystemSettingRepository;
  readonly #uow: AuditedUnitOfWork;

  constructor(settings: SystemSettingRepository, uow: AuditedUnitOfWork) {
    this.#settings = settings;
    this.#uow = uow;
  }

  list(): Promise<SystemSetting[]> {
    return this.#settings.listAll();
  }

  async update(key: string, value: JsonValue, updatedById: string | null): Promise<SystemSetting> {
    const existing = await this.#settings.findByKey(key);
    if (!existing) throw new NotFoundError("Unknown setting");

    return this.#uow.runAudited(
      (updated: SystemSetting) => ({
        action: "settings.update" as const,
        targetType: "system_setting",
        targetId: updated.id,
        outcome: "SUCCESS" as const,
        before: { key, value: existing.value },
        after: { key, value: updated.value },
      }),
      (tx) => this.#settings.upsert(tx, key, value as never, updatedById),
    );
  }
}
