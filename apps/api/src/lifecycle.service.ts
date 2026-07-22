/**
 * Graceful shutdown.
 *
 * Nest's shutdown hooks fire on SIGTERM/SIGINT; this closes the three long-lived
 * connections the API holds so a container stop does not leave a half-open Postgres session
 * or a BullMQ blocking client behind. ET-4's real container stop depends on this being
 * clean.
 */
import { Inject, Injectable, type OnApplicationShutdown } from "@nestjs/common";
import type { SunilPrismaClient } from "@sunil/db";
import type { CounterStore } from "./ratelimit/counter-store.js";
import type { QueuePort } from "./jobs/queue.port.js";
import { TOKENS } from "./tokens.js";

@Injectable()
export class LifecycleService implements OnApplicationShutdown {
  constructor(
    @Inject(TOKENS.Prisma) private readonly prisma: SunilPrismaClient,
    @Inject(TOKENS.CounterStore) private readonly counters: CounterStore,
    @Inject(TOKENS.Queue) private readonly queue: QueuePort,
  ) {}

  async onApplicationShutdown(): Promise<void> {
    await Promise.allSettled([
      this.queue.close(),
      this.counters.close(),
      this.prisma.$disconnect(),
    ]);
  }
}
