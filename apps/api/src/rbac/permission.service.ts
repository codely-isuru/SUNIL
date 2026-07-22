/**
 * Per-request permission resolution (§7.3, Gate 1).
 *
 * One indexed query per request: `user_roles ⋈ role_permissions ⋈ permissions`. The result
 * is memoised **inside the request context only** — there is no cross-request cache in
 * Phase 1, deliberately, because a cache would mean a privilege change did not take effect
 * until it expired. That is exactly the property Gate 1 bought with §6.6, and adding a cache
 * is a new ADR, not an optimisation.
 */
import { hasPermission, type PermissionKey } from "@sunil/core";
import type { TransactionClient, UserRepository } from "@sunil/db";
import { currentContext } from "../common/request-context.js";

export class PermissionService {
  readonly #users: UserRepository;

  constructor(users: UserRepository) {
    this.#users = users;
  }

  async resolve(userId: string): Promise<readonly string[]> {
    const context = currentContext();
    if (context?.permissions && context.session?.userId === userId) return context.permissions;

    const permissions = await this.#users.findEffectivePermissions(userId);
    if (context && context.session?.userId === userId) context.permissions = permissions;
    return permissions;
  }

  /** Same resolution, inside a transaction — the §6.6 before/after snapshots use this. */
  resolveInTransaction(tx: TransactionClient, userId: string): Promise<string[]> {
    return this.#users.findEffectivePermissions(userId, tx);
  }

  async can(userId: string, permission: PermissionKey): Promise<boolean> {
    return hasPermission(await this.resolve(userId), permission);
  }
}
