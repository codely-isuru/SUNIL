/** Shared test doubles. No credential in this file is real — they are sentinels. */
import { SecretNotFoundError, SecretValue, type SecretMetadata, type SecretStore } from "@sunil/core";
import { StaticModelRates } from "../rates.js";
import { UsageRecorder, type UsageRow, type UsageSink } from "../usage.js";

/** A sentinel that is obviously not a live credential but exercises the SecretValue path. */
export const SENTINEL_KEY = "fixture-not-a-real-credential";

export class FakeSecretStore implements SecretStore {
  readonly reads: string[] = [];
  readonly #values: Map<string, string>;

  constructor(values: Record<string, string> = {}) {
    this.#values = new Map(Object.entries(values));
  }

  put(): Promise<SecretMetadata> {
    throw new Error("not used in these tests");
  }

  get(name: string): Promise<SecretValue> {
    this.reads.push(name);
    const value = this.#values.get(name);
    if (value === undefined) return Promise.reject(new SecretNotFoundError(name));
    return Promise.resolve(new SecretValue(name, value));
  }

  rotate(): Promise<SecretMetadata> {
    throw new Error("not used in these tests");
  }

  delete(): Promise<void> {
    throw new Error("not used in these tests");
  }

  describe(): Promise<SecretMetadata> {
    throw new Error("not used in these tests");
  }
}

export class MemoryUsageSink implements UsageSink {
  readonly rows: UsageRow[] = [];

  record(row: UsageRow): Promise<void> {
    this.rows.push(row);
    return Promise.resolve();
  }
}

export function makeRecorder(rates: Record<string, { inputPerMillionUsd: number; outputPerMillionUsd: number }> = {}): {
  recorder: UsageRecorder;
  sink: MemoryUsageSink;
} {
  const sink = new MemoryUsageSink();
  const recorder = new UsageRecorder({ sink, rates: new StaticModelRates(rates) });
  return { recorder, sink };
}
