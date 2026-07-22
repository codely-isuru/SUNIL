/**
 * Idempotency keys on mutating endpoints (SUNIL_ARCHITECTURE §"API conventions").
 *
 * Scope note, stated plainly because it is an interpretation: PHASE1_ARCHITECTURE §13 lists
 * no per-route idempotency requirement — the convention comes from the parent architecture
 * document's API conventions. This is therefore implemented as an OPT-IN, header-driven
 * behaviour on the routes that create durable state, and it changes nothing for a caller
 * that sends no `Idempotency-Key`.
 *
 * Mechanics: the first request under a key stores its status and body; a replay of the same
 * key on the same route by the same principal returns the stored response without
 * re-executing the handler. Keys are scoped by principal + method + path, so one caller's
 * key can never replay another's response.
 */
import {
  Inject,
  Injectable,
  type CallHandler,
  type ExecutionContext,
  type NestInterceptor,
} from "@nestjs/common";
import { ConflictError } from "@sunil/core";
import { from, of, switchMap, tap, type Observable } from "rxjs";
import { headerValue, type HttpRequestLike } from "../common/http.types.js";
import { sha256Hex } from "../common/crypto.js";
import { IDEMPOTENT_METADATA, hasMarker } from "../common/declarations.js";
import { currentContext } from "../common/request-context.js";
import type { CounterStore } from "../ratelimit/counter-store.js";
import { TOKENS } from "../tokens.js";

export const IDEMPOTENCY_HEADER = "idempotency-key";
const RETENTION_SECONDS = 24 * 3600;

@Injectable()
export class IdempotencyInterceptor implements NestInterceptor {
  constructor(@Inject(TOKENS.CounterStore) private readonly store: CounterStore) {}

  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const request = context.switchToHttp().getRequest<HttpRequestLike>();
    if (!hasMarker(context.getHandler(), IDEMPOTENT_METADATA)) return next.handle();

    const key = headerValue(request.headers, IDEMPOTENCY_HEADER);
    if (!key) return next.handle();
    if (key.length > 200) throw new ConflictError("Idempotency-Key is too long");

    const principal = currentContext()?.session?.userId ?? "anonymous";
    const storeKey = `idem:${sha256Hex(`${principal}|${request.method}|${request.url}|${key}`)}`;

    return from(this.store.get(storeKey)).pipe(
      switchMap((cached) => {
        if (cached !== null) {
          // A replay performs no mutation, so the §9.4 tally must not demand a new record.
          const context = currentContext();
          if (context) context.idempotentReplay = true;
          return of(JSON.parse(cached) as unknown);
        }
        return next.handle().pipe(
          tap((value) => {
            void this.store.set(storeKey, JSON.stringify(value ?? null), RETENTION_SECONDS);
          }),
        );
      }),
    );
  }
}
