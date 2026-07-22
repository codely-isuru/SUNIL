/**
 * Guard 4 of 4 — the permission check (§7.3/§7.4, FR-025/FR-026, ET-2).
 *
 * The whole authorisation algebra is `Set.has` (ADR-001): flat `resource:action` strings,
 * concrete rows only, no wildcard grammar at runtime. Roles and grants are DATA, so ET-2 2.5
 * — grant the permission in the database and the same call succeeds with no code change —
 * follows from the design rather than from a special case.
 *
 * Denials carry the status code and a generic body only. No resource-existence detail leaks
 * through an authorisation failure (FR-026).
 */
import { Inject, Injectable, type CanActivate, type ExecutionContext } from "@nestjs/common";
import { ForbiddenError, hasPermission } from "@sunil/core";
import { currentContext } from "../common/request-context.js";
import type { PermissionService } from "../rbac/permission.service.js";
import { TOKENS } from "../tokens.js";

@Injectable()
export class PermissionGuard implements CanActivate {
  constructor(@Inject(TOKENS.PermissionService) private readonly permissions: PermissionService) {}

  async canActivate(_context: ExecutionContext): Promise<boolean> {
    const requestContext = currentContext();
    const declaration = requestContext?.declaration;
    if (!requestContext || !declaration) throw new ForbiddenError("Route carries no declaration");

    if (declaration.kind === "public") return true;
    // `@SelfService()` needs an ACTIVE session and nothing more; the SessionGuard has
    // already established that, and each handler scopes its own work to the caller.
    if (declaration.kind === "self-service") return true;

    const session = requestContext.session;
    if (!session) throw new ForbiddenError("No session");

    const granted = await this.permissions.resolve(session.userId);
    if (!hasPermission(granted, declaration.permission)) {
      throw new ForbiddenError("Permission denied");
    }
    return true;
  }
}
