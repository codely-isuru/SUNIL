/**
 * Health (§13, FR-091).
 *
 * Booleans only. No versions, no connection strings, no error text — an unauthenticated
 * health probe is a reconnaissance surface, and "postgres: down" is the entire budget of
 * information it is allowed to disclose.
 */
import { Controller, Get, Inject } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import type { SunilPrismaClient } from "@sunil/db";
import { Public } from "../common/declarations.js";
import { TOKENS } from "../tokens.js";
import type { QueuePort } from "../jobs/queue.port.js";

type DependencyState = "up" | "down";

interface HealthBody {
  readonly status: "ok" | "degraded";
  readonly deps: { readonly postgres: DependencyState; readonly redis: DependencyState };
}

@ApiTags("health")
@Controller()
export class HealthController {
  constructor(
    @Inject(TOKENS.Prisma) private readonly prisma: SunilPrismaClient,
    @Inject(TOKENS.Queue) private readonly queue: QueuePort,
  ) {}

  @Get("system-health")
  @Public()
  @ApiOperation({ summary: "Liveness of the API and its two dependencies (booleans only)" })
  systemHealth(): Promise<HealthBody> {
    return this.#probe();
  }

  /**
   * Alias. `/api/system-health` is the name §13 and the Compose healthcheck use; `/api/health`
   * exists because it is the conventional probe path and callers reach for it first. Same
   * body, same public declaration, no additional disclosure.
   */
  @Get("health")
  @Public()
  health(): Promise<HealthBody> {
    return this.#probe();
  }

  async #probe(): Promise<HealthBody> {
    const [postgres, redis] = await Promise.all([this.#postgres(), this.queue.ping()]);
    return {
      status: postgres && redis ? "ok" : "degraded",
      deps: { postgres: postgres ? "up" : "down", redis: redis ? "up" : "down" },
    };
  }

  async #postgres(): Promise<boolean> {
    try {
      await this.prisma.$queryRaw`SELECT 1`;
      return true;
    } catch {
      return false;
    }
  }
}
