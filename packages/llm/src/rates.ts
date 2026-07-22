/**
 * Cost estimation inputs (FR-064): "the per-model rates come from configuration/data, not
 * hard-coded constants in call sites".
 *
 * There is no rate table in this file. Rates are read from `SystemSetting["llm.modelRates"]`,
 * which the bootstrap seeds EMPTY on purpose — an unknown model estimates 0.00 rather than
 * inventing a price. `estimateCostUsd` in `@sunil/core` does the arithmetic.
 */
import { ModelRatesSchema, type ModelRates } from "@sunil/core";
import type { SystemSettingRepository } from "@sunil/db";
import type { LlmLogger } from "./logging.js";

/** The single settings key holding token rates. */
export const MODEL_RATES_SETTING_KEY = "llm.modelRates" as const;

export interface ModelRatesSource {
  get(): Promise<ModelRates>;
}

/** Rates that never change — used by tests and by callers that have already loaded them. */
export class StaticModelRates implements ModelRatesSource {
  readonly #rates: ModelRates;

  constructor(rates: ModelRates) {
    this.#rates = ModelRatesSchema.parse(rates);
  }

  get(): Promise<ModelRates> {
    return Promise.resolve(this.#rates);
  }
}

/**
 * Reads `llm.modelRates` from the settings table, with a short TTL cache so a burst of LLM
 * calls does not become a burst of settings queries. A malformed or absent row degrades to
 * "no rates" (cost 0.00) with a warning — it must never fail an LLM call.
 */
export class SystemSettingModelRates implements ModelRatesSource {
  readonly #settings: SystemSettingRepository;
  readonly #logger: LlmLogger | undefined;
  readonly #ttlMs: number;
  readonly #now: () => number;
  #cache: { rates: ModelRates; loadedAt: number } | undefined;

  constructor(
    settings: SystemSettingRepository,
    options: { logger?: LlmLogger; ttlMs?: number; now?: () => number } = {},
  ) {
    this.#settings = settings;
    this.#logger = options.logger;
    this.#ttlMs = options.ttlMs ?? 60_000;
    this.#now = options.now ?? Date.now;
  }

  async get(): Promise<ModelRates> {
    const now = this.#now();
    if (this.#cache && now - this.#cache.loadedAt < this.#ttlMs) return this.#cache.rates;

    let rates: ModelRates = {};
    try {
      const row = await this.#settings.findByKey(MODEL_RATES_SETTING_KEY);
      const parsed = ModelRatesSchema.safeParse(row?.value ?? {});
      if (parsed.success) {
        rates = parsed.data;
      } else {
        this.#logger?.warn(
          { settingKey: MODEL_RATES_SETTING_KEY, issues: parsed.error.issues.map((i) => i.path.join(".")) },
          "llm.modelRates is malformed; estimating cost as 0.00",
        );
      }
    } catch (error) {
      this.#logger?.warn(
        { settingKey: MODEL_RATES_SETTING_KEY, error: error instanceof Error ? error.name : "unknown" },
        "could not read llm.modelRates; estimating cost as 0.00",
      );
    }

    this.#cache = { rates, loadedAt: now };
    return rates;
  }
}
