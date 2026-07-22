/**
 * The counter substrate for rate limiting and brute-force lockout (§6.3, §12.2).
 *
 * Redis owns these counters in every real deployment — they are ephemeral, they must be
 * shared across API instances, and ADR-002's AOF configuration is what persists them. The
 * interface exists so the *policy* (thresholds, windows, key shapes) can be exercised in a
 * unit test without a container, while the shipping wiring is always the Redis
 * implementation.
 */
export interface CounterWindow {
  readonly count: number;
  readonly ttlSeconds: number;
}

export interface CounterStore {
  /** Fixed-window `INCR` + `EXPIRE` (§6.3). Returns the post-increment count and its TTL. */
  increment(key: string, windowSeconds: number): Promise<CounterWindow>;
  /** Remaining TTL of a marker key, or `null` when it does not exist. */
  ttl(key: string): Promise<number | null>;
  setMarker(key: string, ttlSeconds: number): Promise<void>;
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds: number): Promise<void>;
  delete(key: string): Promise<void>;
  close(): Promise<void>;
}

/**
 * In-process implementation. Used by policy unit tests and as the documented fallback for a
 * single-instance developer run; it is never a substitute for Redis in a deployed stack
 * because it is neither shared nor persisted.
 */
export class InMemoryCounterStore implements CounterStore {
  readonly #entries = new Map<string, { value: string; expiresAt: number }>();

  #sweep(now: number): void {
    for (const [key, entry] of this.#entries) {
      if (entry.expiresAt <= now) this.#entries.delete(key);
    }
  }

  async increment(key: string, windowSeconds: number): Promise<CounterWindow> {
    const now = Date.now();
    this.#sweep(now);
    const existing = this.#entries.get(key);
    if (existing) {
      const next = Number(existing.value) + 1;
      existing.value = String(next);
      return { count: next, ttlSeconds: Math.ceil((existing.expiresAt - now) / 1000) };
    }
    this.#entries.set(key, { value: "1", expiresAt: now + windowSeconds * 1000 });
    return { count: 1, ttlSeconds: windowSeconds };
  }

  async ttl(key: string): Promise<number | null> {
    const now = Date.now();
    this.#sweep(now);
    const entry = this.#entries.get(key);
    if (!entry) return null;
    return Math.max(1, Math.ceil((entry.expiresAt - now) / 1000));
  }

  async setMarker(key: string, ttlSeconds: number): Promise<void> {
    await this.set(key, "1", ttlSeconds);
  }

  async get(key: string): Promise<string | null> {
    this.#sweep(Date.now());
    return this.#entries.get(key)?.value ?? null;
  }

  async set(key: string, value: string, ttlSeconds: number): Promise<void> {
    this.#entries.set(key, { value, expiresAt: Date.now() + ttlSeconds * 1000 });
  }

  async delete(key: string): Promise<void> {
    this.#entries.delete(key);
  }

  async close(): Promise<void> {
    this.#entries.clear();
  }
}
