/**
 * The Redis connection (FR-080, ADR-002).
 *
 * `maxRetriesPerRequest: null` is REQUIRED by BullMQ's blocking commands — without it a
 * blocking `BRPOPLPUSH` is aborted mid-wait and jobs appear to vanish.
 *
 * Redis unavailable at start is a RETRY-WITH-BACKOFF condition with a clear log line, never a
 * silent exit and never a crash loop without a message (FR-080, NFR-010).
 *
 * Warning §18.4: `maxmemory-policy noeviction` on the server is load-bearing. Eviction
 * silently destroys BullMQ keys — that is the failure ET-4 exists to prevent. It is set on the
 * container (Compose), not here, and must not be "fixed" under memory pressure.
 */
import { Redis } from "ioredis";
import type { AppLogger } from "./logger.js";

export const MAX_BACKOFF_MS = 5_000;

export function createRedisConnection(url: string, logger: AppLogger): Redis {
  const connection = new Redis(url, {
    // BullMQ requirement — do not change.
    maxRetriesPerRequest: null,
    enableReadyCheck: true,
    retryStrategy: (attempt) => {
      const delay = Math.min(attempt * 500, MAX_BACKOFF_MS);
      logger.warn(
        { attempt, delayMs: delay },
        "redis is unavailable; retrying with backoff (queue work is paused, not lost)",
      );
      return delay;
    },
  });

  connection.on("error", (error: Error) => {
    // The message, never the URL: `REDIS_URL` can carry credentials.
    logger.error({ error: error.name }, "redis connection error");
  });
  connection.on("ready", () => logger.info({}, "redis connection ready"));
  connection.on("end", () => logger.warn({}, "redis connection closed"));

  return connection;
}

/**
 * Assert the durability posture ET-4 depends on. Logged loudly rather than thrown: a worker
 * that refuses to start because of a config-read failure is worse than one that runs and
 * complains. `noeviction` is checked because an evicting Redis loses jobs silently.
 */
export async function verifyPersistencePosture(connection: Redis, logger: AppLogger): Promise<{
  appendonly: string | undefined;
  maxmemoryPolicy: string | undefined;
}> {
  try {
    const [, appendonly] = (await connection.config("GET", "appendonly")) as string[];
    const [, maxmemoryPolicy] = (await connection.config("GET", "maxmemory-policy")) as string[];

    if (maxmemoryPolicy !== "noeviction") {
      logger.error(
        { maxmemoryPolicy },
        "redis maxmemory-policy is not `noeviction`: BullMQ state can be evicted and jobs lost silently (ADR-002 / §18.4)",
      );
    }
    if (appendonly !== "yes") {
      logger.error(
        { appendonly },
        "redis AOF persistence is off: queued and delayed jobs will not survive a restart (ADR-002)",
      );
    }
    if (maxmemoryPolicy === "noeviction" && appendonly === "yes") {
      logger.info(
        { appendonly, maxmemoryPolicy },
        "redis durability posture verified: AOF on and eviction disabled (ADR-002)",
      );
    }
    return { appendonly, maxmemoryPolicy };
  } catch (error) {
    logger.warn(
      { error: error instanceof Error ? error.name : "unknown" },
      "could not read the redis persistence configuration",
    );
    return { appendonly: undefined, maxmemoryPolicy: undefined };
  }
}
