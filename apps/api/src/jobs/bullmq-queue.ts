/**
 * BullMQ implementation of the API's producer/observer queue port (§12.1, §12.5).
 *
 * Queue names and default job options come from `@sunil/core` — there is one topology
 * definition in the repository and this file is not a second one. Connections are created
 * lazily so a stack whose Redis is briefly unavailable still starts and still reports
 * `redis: down` on the health endpoint rather than crash-looping.
 */
import { Queue } from "bullmq";
import { Redis } from "ioredis";
import { DEFAULT_JOB_OPTIONS, JOB_NAMES, QUEUE_NAMES, type QueueName } from "@sunil/core";
import type { QueueCounts, QueuePort, QueueStatus, SchedulerSummary } from "./queue.port.js";

export class BullmqQueuePort implements QueuePort {
  readonly #redisUrl: string;
  #connection: Redis | undefined;
  readonly #queues = new Map<QueueName, Queue>();

  constructor(redisUrl: string) {
    this.#redisUrl = redisUrl;
  }

  #conn(): Redis {
    this.#connection ??= new Redis(this.#redisUrl, {
      // BullMQ requires this to be null on its blocking clients.
      maxRetriesPerRequest: null,
    });
    this.#connection.on("error", () => undefined);
    return this.#connection;
  }

  #queue(name: QueueName): Queue {
    let queue = this.#queues.get(name);
    if (!queue) {
      queue = new Queue(name, { connection: this.#conn(), defaultJobOptions: DEFAULT_JOB_OPTIONS });
      this.#queues.set(name, queue);
    }
    return queue;
  }

  async enqueueAgentRun(args: {
    agentId: string;
    taskId: string;
    correlationId: string;
  }): Promise<{ jobId: string }> {
    const job = await this.#queue(QUEUE_NAMES.agents).add(JOB_NAMES.agentRun, args);
    return { jobId: String(job.id) };
  }

  async status(): Promise<QueueStatus> {
    const queues: QueueCounts[] = [];
    const schedulers: SchedulerSummary[] = [];

    for (const name of [QUEUE_NAMES.system, QUEUE_NAMES.agents] as const) {
      const queue = this.#queue(name);
      const counts = await queue.getJobCounts(
        "waiting",
        "active",
        "completed",
        "failed",
        "delayed",
      );
      queues.push({
        queue: name,
        waiting: counts["waiting"] ?? 0,
        active: counts["active"] ?? 0,
        completed: counts["completed"] ?? 0,
        failed: counts["failed"] ?? 0,
        delayed: counts["delayed"] ?? 0,
      });

      const defined = await queue.getJobSchedulers(0, 50, true);
      for (const scheduler of defined) {
        schedulers.push({
          id: String(scheduler.key ?? scheduler.id ?? ""),
          name: scheduler.name ?? null,
          every: scheduler.every ? Number(scheduler.every) : null,
          next: scheduler.next ? Number(scheduler.next) : null,
        });
      }
    }

    return { queues, schedulers };
  }

  async ping(): Promise<boolean> {
    try {
      const pong = await this.#conn().ping();
      return pong === "PONG";
    } catch {
      return false;
    }
  }

  async close(): Promise<void> {
    for (const queue of this.#queues.values()) {
      await queue.close();
    }
    this.#queues.clear();
    this.#connection?.disconnect();
    this.#connection = undefined;
  }
}
