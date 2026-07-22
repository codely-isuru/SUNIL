/**
 * Guard 3 of 4 — rate limiting (§6.3, FR-029).
 *
 * Two fixed windows, both thresholds from configuration (§16, Gate-1 defaults):
 *   - 100 requests/minute per SESSION, for every authenticated route;
 *   - 20 requests/minute per IP on routes marked `@AuthEndpoint()`, which is the brute-force
 *     ceiling that applies before a session exists.
 *
 * Exceeding either returns 429 with `Retry-After` and an audited `rate_limited` denial.
 *
 * A counter-store failure is treated as fail-OPEN for the limiter specifically: rate
 * limiting is an availability control, not an authorisation control, and taking the API down
 * because Redis blipped would be the wrong trade. Authorisation itself never fails open.
 */
import { Inject, Injectable, type CanActivate, type ExecutionContext } from "@nestjs/common";
import { RateLimitedError } from "@sunil/core";
import type { HttpRequestLike } from "../common/http.types.js";
import { AUTH_ENDPOINT_METADATA, hasMarker } from "../common/declarations.js";
import { currentContext } from "../common/request-context.js";
import type { ApiConfig } from "../config/api-config.js";
import type { CounterStore } from "../ratelimit/counter-store.js";
import { TOKENS } from "../tokens.js";

const WINDOW_SECONDS = 60;

@Injectable()
export class RateLimitGuard implements CanActivate {
  constructor(
    @Inject(TOKENS.CounterStore) private readonly counters: CounterStore,
    @Inject(TOKENS.Config) private readonly config: ApiConfig,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<HttpRequestLike>();
    const handler = context.getHandler();

    if (hasMarker(handler, AUTH_ENDPOINT_METADATA)) {
      const ip = request.ip || "unknown";
      await this.#check(`ratelimit:authip:${ip}`, this.config.rateAuthIpPerMinute);
    }

    const session = currentContext()?.session;
    if (session) {
      await this.#check(`ratelimit:session:${session.id}`, this.config.rateSessionPerMinute);
    }

    return true;
  }

  async #check(key: string, limit: number): Promise<void> {
    let window: { count: number; ttlSeconds: number };
    try {
      window = await this.counters.increment(key, WINDOW_SECONDS);
    } catch {
      return; // see the fail-open note above
    }
    if (window.count > limit) {
      throw new RateLimitedError(Math.max(1, window.ttlSeconds));
    }
  }
}
