/**
 * `RoleAssignmentService` — the §6.6 choke point (Gate 1).
 *
 * This is the ONLY code in `apps/api` permitted to write `user_roles`. Everything the
 * Gate-1 decision requires happens inside ONE audited transaction:
 *
 *   1. resolve the effective permission set BEFORE
 *   2. apply the role change
 *   3. resolve the effective permission set AFTER — same transaction, so it reads the rows
 *      the step above just wrote
 *   4. write the `user.role.change` record with both sets
 *   5. if ANY permission was lost, revoke every session of that user, reason
 *      `privilege_reduction`
 *
 * Steps 3–5 are only expressible because `runAudited`'s spec may be a FUNCTION of
 * `(result, tx)`: the audit entry can reference state produced inside the transaction. The
 * revocation and the audit record therefore commit atomically with the role change — there
 * is no window in which the role is reduced but the session is still live, and no way for
 * the revocation to succeed while its audit record fails.
 *
 * Increases need no revocation: permissions are resolved per request (§7.3), so a grant is
 * live on the caller's very next request.
 */
import {
  ForbiddenError,
  InvariantViolationError,
  NotFoundError,
  OWNER_ROLE_ID,
} from "@sunil/core";
import type { SunilPrismaClient, TransactionClient } from "@sunil/db";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import type { PermissionService } from "./permission.service.js";

export interface RoleChangeResult {
  readonly userId: string;
  readonly before: readonly string[];
  readonly after: readonly string[];
  readonly removed: readonly string[];
  readonly added: readonly string[];
  readonly sessionsRevoked: number;
}

export class RoleAssignmentService {
  readonly #prisma: SunilPrismaClient;
  readonly #permissions: PermissionService;
  readonly #uow: AuditedUnitOfWork;

  constructor(
    prisma: SunilPrismaClient,
    permissions: PermissionService,
    uow: AuditedUnitOfWork,
  ) {
    this.#prisma = prisma;
    this.#permissions = permissions;
    this.#uow = uow;
  }

  async changeRoles(userId: string, roleIds: readonly string[]): Promise<RoleChangeResult> {
    const user = await this.#prisma.user.findUnique({ where: { id: userId } });
    if (!user) throw new NotFoundError("User not found");

    // ADR-001: exactly one owner, enforced at three layers. The API is layer (b) and must
    // refuse before the partial unique index has to (layer (c)).
    if (roleIds.includes(OWNER_ROLE_ID)) {
      throw new InvariantViolationError("The owner role cannot be assigned through the API");
    }
    const targetIsOwner = await this.#prisma.userRole.findFirst({
      where: { userId, roleId: OWNER_ROLE_ID },
    });
    if (targetIsOwner) {
      throw new ForbiddenError("The owner account's roles cannot be changed");
    }

    const distinct = [...new Set(roleIds)];
    const roles = await this.#prisma.role.findMany({ where: { id: { in: distinct } } });
    if (roles.length !== distinct.length) throw new NotFoundError("Unknown role");

    return this.#uow.runAudited<RoleChangeResult>(
      (result) => ({
        action: "user.role.change",
        targetType: "user",
        targetId: result.userId,
        outcome: "SUCCESS",
        before: { permissions: result.before },
        after: {
          permissions: result.after,
          removed: result.removed,
          added: result.added,
          sessionsRevoked: result.sessionsRevoked,
        },
      }),
      async (tx: TransactionClient) => {
        const before = await this.#permissions.resolveInTransaction(tx, userId);

        await tx.userRole.deleteMany({ where: { userId } });
        for (const roleId of distinct) {
          await tx.userRole.create({ data: { userId, roleId } });
        }

        const after = await this.#permissions.resolveInTransaction(tx, userId);

        const afterSet = new Set(after);
        const beforeSet = new Set(before);
        const removed = before.filter((p) => !afterSet.has(p));
        const added = after.filter((p) => !beforeSet.has(p));

        // §6.6 step 5 — ANY loss revokes, in this transaction.
        let sessionsRevoked = 0;
        if (removed.length > 0) {
          const result = await tx.session.updateMany({
            where: { userId, state: { in: ["ACTIVE", "PENDING_MFA"] } },
            data: {
              state: "REVOKED",
              revokedAt: new Date(),
              revokedReason: "privilege_reduction",
            },
          });
          sessionsRevoked = result.count;
        }

        return { userId, before, after, removed, added, sessionsRevoked };
      },
    );
  }
}
