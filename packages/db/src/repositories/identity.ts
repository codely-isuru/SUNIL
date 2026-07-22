/**
 * Thin identity repositories.
 *
 * "Thin" is the contract: they translate a domain question into one Prisma query and no
 * more. Business rules (the §6.6 role-change choke point, lockout policy, MFA replay
 * windows) live in `apps/api` services, not here — and every WRITE takes a
 * `TransactionClient`, because writes belong to a `UnitOfWork.runAudited` call.
 */
import type {
  Invitation,
  MfaCredential,
  MfaRecoveryCode,
  Permission,
  Prisma,
  Role,
  RolePermission,
  Session,
  User,
  UserRole,
} from "@prisma/client";
import type { PageRequest, Paged } from "@sunil/core";
import type { SunilPrismaClient, TransactionClient } from "../client.js";

/**
 * Every model in the §5.2 identity group, re-exported.
 *
 * Consumers must never `import type { … } from "@prisma/client"` — the dependency fence
 * forbids it — so a model type that is not re-exported here forces a hand-written
 * structural duplicate in `apps/api`, which then silently drifts from the schema. The rule
 * is therefore: EVERY Phase 1 model type is re-exported from `@sunil/db`, not just the ones
 * a repository happens to return today.
 */
export type {
  Invitation,
  MfaCredential,
  MfaRecoveryCode,
  Permission,
  Role,
  RolePermission,
  Session,
  User,
  UserRole,
};

export class UserRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  /** Email is normalised (trim + lowercase) at the Zod boundary in `@sunil/core`. */
  findByEmail(email: string): Promise<User | null> {
    return this.#prisma.user.findUnique({ where: { email } });
  }

  findById(id: string): Promise<User | null> {
    return this.#prisma.user.findUnique({ where: { id } });
  }

  async listPaged(page: PageRequest): Promise<Paged<User>> {
    const skip = (page.page - 1) * page.pageSize;
    const [items, total] = await Promise.all([
      this.#prisma.user.findMany({ orderBy: { createdAt: "desc" }, skip, take: page.pageSize }),
      this.#prisma.user.count(),
    ]);
    return {
      items,
      page: page.page,
      pageSize: page.pageSize,
      total,
      hasMore: skip + items.length < total,
    };
  }

  /**
   * Effective permissions, resolved per request in ONE indexed query
   * (`user_roles ⋈ role_permissions ⋈ permissions`, §7.3). There is no cross-request
   * permission cache in Phase 1 — adding one is a new ADR because it interacts with §6.6.
   */
  async findEffectivePermissions(
    userId: string,
    client: SunilPrismaClient | TransactionClient = this.#prisma,
  ): Promise<string[]> {
    const rows = await client.permission.findMany({
      where: { rolePermissions: { some: { role: { userRoles: { some: { userId } } } } } },
      select: { key: true },
      orderBy: { key: "asc" },
    });
    return rows.map((row) => row.key);
  }

  findRoleIds(userId: string): Promise<{ roleId: string }[]> {
    return this.#prisma.userRole.findMany({ where: { userId }, select: { roleId: true } });
  }

  create(tx: TransactionClient, data: Prisma.UserCreateInput): Promise<User> {
    return tx.user.create({ data });
  }

  update(tx: TransactionClient, id: string, data: Prisma.UserUpdateInput): Promise<User> {
    return tx.user.update({ where: { id }, data });
  }
}

export class RoleRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  listAll(): Promise<Role[]> {
    return this.#prisma.role.findMany({ orderBy: { slug: "asc" } });
  }

  findBySlug(slug: string): Promise<Role | null> {
    return this.#prisma.role.findUnique({ where: { slug } });
  }

  findById(id: string): Promise<Role | null> {
    return this.#prisma.role.findUnique({ where: { id } });
  }

  async listPermissionKeys(roleId: string): Promise<string[]> {
    const rows = await this.#prisma.rolePermission.findMany({
      where: { roleId },
      select: { permission: { select: { key: true } } },
    });
    return rows.map((row) => row.permission.key);
  }

  /** How many principals hold a given role — the owner-count invariant reads this. */
  countHolders(roleId: string): Promise<number> {
    return this.#prisma.userRole.count({ where: { roleId } });
  }
}

export class PermissionRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  listAll() {
    return this.#prisma.permission.findMany({ orderBy: { key: "asc" } });
  }
}

export class SessionRepository {
  readonly #prisma: SunilPrismaClient;

  constructor(prisma: SunilPrismaClient) {
    this.#prisma = prisma;
  }

  /** The raw cookie token is never stored; callers hash it first (§6.1). */
  findByTokenHash(tokenHash: string): Promise<Session | null> {
    return this.#prisma.session.findUnique({ where: { tokenHash } });
  }

  listForUser(userId: string): Promise<Session[]> {
    return this.#prisma.session.findMany({
      where: { userId },
      orderBy: { createdAt: "desc" },
    });
  }

  create(tx: TransactionClient, data: Prisma.SessionCreateInput): Promise<Session> {
    return tx.session.create({ data });
  }

  /**
   * Sliding-refresh bookkeeping. Not a security decision — expiry is enforced at validation
   * time regardless — so it is deliberately NOT an audited mutation (§6.2).
   */
  touch(id: string, idleExpiresAt: Date): Promise<Session> {
    return this.#prisma.session.update({
      where: { id },
      data: { lastSeenAt: new Date(), idleExpiresAt },
    });
  }

  revoke(tx: TransactionClient, id: string, reason: string): Promise<Session> {
    return tx.session.update({
      where: { id },
      data: { state: "REVOKED", revokedAt: new Date(), revokedReason: reason },
    });
  }

  /** Used by the §6.6 privilege-reduction hook, inside the same audited transaction. */
  revokeAllForUser(
    tx: TransactionClient,
    userId: string,
    reason: string,
    exceptSessionId?: string,
  ): Promise<{ count: number }> {
    return tx.session.updateMany({
      where: {
        userId,
        state: { in: ["ACTIVE", "PENDING_MFA"] },
        ...(exceptSessionId ? { id: { not: exceptSessionId } } : {}),
      },
      data: { state: "REVOKED", revokedAt: new Date(), revokedReason: reason },
    });
  }

  /** Bookkeeping sweep (§6.2) — expiry is enforced at validation time regardless. */
  markExpired(tx: TransactionClient, now: Date): Promise<{ count: number }> {
    return tx.session.updateMany({
      where: {
        state: { in: ["ACTIVE", "PENDING_MFA"] },
        OR: [{ idleExpiresAt: { lt: now } }, { absoluteExpiresAt: { lt: now } }],
      },
      data: { state: "REVOKED", revokedAt: now, revokedReason: "expired_sweep" },
    });
  }
}
