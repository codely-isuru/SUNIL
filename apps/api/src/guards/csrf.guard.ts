/**
 * Guard 2 of 4 — CSRF (§6.5, ADR-009, FR-028, ET-1 1.9).
 *
 * Synchronizer token, delivered out-of-cookie: the per-session `csrfSecret` is handed to the
 * client in the login / MFA-verify response body and by `GET /api/auth/me`, and must come
 * back in `X-CSRF-Token` on every mutating request. A cross-site attacker's request carries
 * the cookie automatically but cannot read the token, so the cookie alone can never
 * authorise a mutation.
 *
 * Safe methods are exempt (FR-028). Mutating routes with no session are the pre-session
 * public ones (login, MFA verify, invitation accept) — there is no session secret to bind to
 * yet, which is why ADR-009 binds the token to the session rather than to the request.
 */
import { Inject, Injectable, type CanActivate, type ExecutionContext } from "@nestjs/common";
import { CsrfError } from "@sunil/core";
import { headerValue, type HttpRequestLike } from "../common/http.types.js";
import { constantTimeEquals } from "../common/crypto.js";
import { currentContext } from "../common/request-context.js";
import { TOKENS } from "../tokens.js";
import type { ApiConfig } from "../config/api-config.js";

export const CSRF_HEADER = "x-csrf-token";
const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

export function isMutatingMethod(method: string): boolean {
  return MUTATING_METHODS.has(method.toUpperCase());
}

@Injectable()
export class CsrfGuard implements CanActivate {
  constructor(@Inject(TOKENS.Config) private readonly _config: ApiConfig) {}

  async canActivate(context: ExecutionContext): Promise<boolean> {
    const request = context.switchToHttp().getRequest<HttpRequestLike>();
    if (!isMutatingMethod(request.method)) return true;

    const session = currentContext()?.session;
    if (!session) return true;

    const presented = headerValue(request.headers, CSRF_HEADER);
    if (!presented || !constantTimeEquals(presented, session.csrfSecret)) {
      throw new CsrfError("Missing or invalid CSRF token");
    }
    return true;
  }
}
