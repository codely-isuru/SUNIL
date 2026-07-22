/**
 * The request-scoped audit tally (§9.4) — "coverage enforced, not remembered".
 *
 * §9.4 gives audit coverage two independent checks. The build-time one is the route
 * enumeration test (every mutating route carries `@Audited`). This is the RUN-TIME one: a
 * mutating request that returns successfully having written ZERO audit records is not
 * allowed to leave the process. The tally is incremented by `AuditedUnitOfWork` after a
 * transaction commits, so an entry inside a rolled-back transaction never satisfies it.
 *
 * A decorator that exists but is never honoured is exactly the failure mode this catches:
 * the enumeration test proves the metadata is present, the tally proves a record was
 * actually written.
 */
import {
  Inject,
  Injectable,
  type CallHandler,
  type ExecutionContext,
  type NestInterceptor,
} from "@nestjs/common";
import { InternalError } from "@sunil/core";
import { map, type Observable } from "rxjs";
import type { HttpRequestLike } from "../common/http.types.js";
import { currentContext } from "../common/request-context.js";
import { isMutatingMethod } from "../guards/csrf.guard.js";
import { readAuditActions } from "../common/declarations.js";
import type { ApiConfig } from "../config/api-config.js";
import { TOKENS } from "../tokens.js";

@Injectable()
export class AuditTallyInterceptor implements NestInterceptor {
  constructor(@Inject(TOKENS.Config) private readonly config: ApiConfig) {}

  intercept(context: ExecutionContext, next: CallHandler): Observable<unknown> {
    const request = context.switchToHttp().getRequest<HttpRequestLike>();
    const mutating = isMutatingMethod(request.method);
    const declaredActions = readAuditActions(context.getHandler());
    const requestContext = currentContext();
    if (requestContext && declaredActions.length > 0) {
      requestContext.auditAction = declaredActions[0]!;
    }

    return next.handle().pipe(
      map((value) => {
        // Production keeps the build-time enumeration test and the fence; the runtime
        // assertion is a dev/test control (§9.4) and must not turn an audit-store hiccup
        // into a 500 for a user whose mutation actually committed and WAS recorded.
        if (!mutating || this.config.isProduction) return value;
        if (currentContext()?.idempotentReplay) return value;
        const tally = currentContext()?.auditWrites ?? 0;
        if (tally === 0) {
          throw new InternalError(
            `Mutating route ${request.method} ${request.url} produced no audit record`,
          );
        }
        return value;
      }),
    );
  }
}
