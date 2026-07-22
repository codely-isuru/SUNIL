/**
 * Guard 1 of 4 — session validation and the §7.4 default-deny gate.
 *
 * Two jobs, in this order:
 *
 *  1. **Read the route's declaration.** A handler with no declaration, or with more than
 *     one, is rejected 403 BEFORE it runs. Absence of a declaration is denial, not
 *     exposure — that is §7.4 layer 1, and it is why a forgotten decorator cannot quietly
 *     ship an open endpoint.
 *  2. **Validate the session** against the row on every request (no cache, §6.2), attach it
 *     to the request context, and reject 401 when a non-public route has no ACTIVE session.
 *
 * A `PENDING_MFA` session authenticates nothing except `/api/auth/mfa/verify`, which is
 * `@Public()` and reads the session from the context itself.
 */
import { Inject, Injectable, type CanActivate, type ExecutionContext } from "@nestjs/common";
import { ForbiddenError, UnauthenticatedError } from "@sunil/core";
import { headerValue, type HttpRequestLike } from "../common/http.types.js";
import { parseCookies } from "../common/cookies.js";
import { resolveDeclaration } from "../common/declarations.js";
import { currentContext } from "../common/request-context.js";
import type { ApiConfig } from "../config/api-config.js";
import type { SessionService } from "../auth/session.service.js";
import { TOKENS } from "../tokens.js";

@Injectable()
export class SessionGuard implements CanActivate {
  constructor(
    @Inject(TOKENS.SessionService) private readonly sessions: SessionService,
    @Inject(TOKENS.Config) private readonly config: ApiConfig,
  ) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<HttpRequestLike>();
    const requestContext = currentContext();
    if (!requestContext) {
      // The context hook runs on every request; its absence means the app was assembled
      // wrongly. Fail closed rather than proceed unaudited.
      throw new ForbiddenError("Request context unavailable");
    }

    const declaration = resolveDeclaration(context.getHandler());
    requestContext.declaration = declaration;
    if (!declaration) throw new ForbiddenError("Route carries no access declaration");

    const cookies = parseCookies(headerValue(request.headers, "cookie"));
    const token = cookies[this.config.cookieName];
    if (token) {
      const session = await this.sessions.validate(token);
      if (session) {
        requestContext.session = session;
        requestContext.actor = {
          type: "HUMAN",
          id: session.user.id,
          label: session.user.email,
        };
      }
    }

    if (declaration.kind === "public") return true;

    const session = requestContext.session;
    if (!session) throw new UnauthenticatedError("No valid session");
    if (session.state !== "ACTIVE") throw new UnauthenticatedError("Session is not established");

    return true;
  }
}
