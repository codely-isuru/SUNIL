/**
 * Redis-backed counters (§6.3, §12.2, ADR-002).
 *
 * `INCR` + `EXPIRE` in one pipeline is the fixed window; the TTL is set only on the first
 * increment so a burst cannot keep extending its own window.
 */
import { Redis } from "ioredis";
import type { CounterStore, CounterWindow } from "./counter-store.js";

export class RedisCounterStore implements CounterStore {
  readonly #redis: Redis;
  /**
   * Namespace for every key this store writes. Empty in a deployed stack; the test harness
   * sets a per-app value so two API instances sharing one Redis cannot collide on a counter.
   */
  readonly #prefix: string;

  constructor(redisUrl: string, options: { prefix?: string } = {}) {
    this.#prefix = options.prefix ?? "";
    this.#redis = new Redis(redisUrl, {
      maxRetriesPerRequest: 2,
      lazyConnect: false,
      enableOfflineQueue: true,
    });
    // A connection error must not crash the process: the guard treats a counter failure as
    // fail-closed at the request level, which is handled by the caller.
    this.#redis.on("error", () => undefined);
  }

  #key(key: string): string {
    return `${this.#prefix}${key}`;
  }

  async increment(key: string, windowSeconds: number): Promise<CounterWindow> {
    const full = this.#key(key);
    const results = await this.#redis
      .multi()
      .incr(full)
      .expire(full, windowSeconds, "NX")
      .ttl(full)
      .exec();

    const count = Number(results?.[0]?.[1] ?? 0);
    const ttl = Number(results?.[2]?.[1] ?? windowSeconds);
    return { count, ttlSeconds: ttl > 0 ? ttl : windowSeconds };
  }

  async ttl(key: string): Promise<number | null> {
    const ttl = await this.#redis.ttl(this.#key(key));
    // -2 = no key, -1 = key without expiry (never written by this store).
    if (ttl === -2) return null;
    return ttl > 0 ? ttl : 1;
  }

  async setMarker(key: string, ttlSeconds: number): Promise<void> {
    await this.#redis.set(this.#key(key), "1", "EX", ttlSeconds);
  }

  async get(key: string): Promise<string | null> {
    return this.#redis.get(this.#key(key));
  }

  async set(key: string, value: string, ttlSeconds: number): Promise<void> {
    await this.#redis.set(this.#key(key), value, "EX", ttlSeconds);
  }

  async delete(key: string): Promise<void> {
    await this.#redis.del(this.#key(key));
  }

  async close(): Promise<void> {
    this.#redis.disconnect();
  }
}
