/**
 * User administration and self-service (§13, FR-011/FR-024/FR-030).
 *
 * Two invariants worth naming:
 *  - `UserSummary` is the only projection that leaves this service. `passwordHash` is never
 *    selected into a response shape, at any status code (FR-011).
 *  - An admin operation may never target the owner account (§7.2). That is checked on the
 *    TARGET, not on the caller's permission set, because `user:update` legitimately exists
 *    on the admin role.
 */
import {
  ForbiddenError,
  NotFoundError,
  OWNER_ROLE_ID,
  UnauthenticatedError,
  type PageRequest,
  type Paged,
  type SessionRevokeReason,
  type UserStatus,
  type UserSummary,
} from "@sunil/core";
import {
  hashPassword,
  verifyPassword,
  type SunilPrismaClient,
  type User,
  type UserRepository,
} from "@sunil/db";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import type { DenialRecorder } from "../audit/denial-recorder.js";
import type { SessionService } from "../auth/session.service.js";
import type { LoginService } from "../auth/login.service.js";

export function toUserSummary(user: User): UserSummary {
  return {
    id: user.id,
    email: user.email,
    displayName: user.displayName,
    status: user.status,
    timezone: user.timezone,
    mfaEnabled: user.mfaEnabled,
    createdAt: user.createdAt.toISOString(),
  };
}

export interface UserUpdateInput {
  readonly displayName?: string;
  readonly status?: UserStatus;
  readonly timezone?: string;
}

export class UserService {
  readonly #prisma: SunilPrismaClient;
  readonly #users: UserRepository;
  readonly #uow: AuditedUnitOfWork;
  readonly #denials: DenialRecorder;
  readonly #sessions: SessionService;
  readonly #logins: LoginService;

  constructor(
    prisma: SunilPrismaClient,
    users: UserRepository,
    uow: AuditedUnitOfWork,
    denials: DenialRecorder,
    sessions: SessionService,
    logins: LoginService,
  ) {
    this.#prisma = prisma;
    this.#users = users;
    this.#uow = uow;
    this.#denials = denials;
    this.#sessions = sessions;
    this.#logins = logins;
  }

  async list(page: PageRequest): Promise<Paged<UserSummary>> {
    const result = await this.#users.listPaged(page);
    return { ...result, items: result.items.map(toUserSummary) };
  }

  /** Role assignments for a user — `GET /api/auth/me` renders the caller's own roles. */
  roleIdsFor(userId: string): Promise<{ roleId: string }[]> {
    return this.#users.findRoleIds(userId);
  }

  async get(id: string): Promise<UserSummary> {
    const user = await this.#users.findById(id);
    if (!user) throw new NotFoundError("User not found");
    return toUserSummary(user);
  }

  async #assertNotOwner(userId: string): Promise<void> {
    const owner = await this.#prisma.userRole.findFirst({
      where: { userId, roleId: OWNER_ROLE_ID },
    });
    if (owner) throw new ForbiddenError("The owner account cannot be modified this way");
  }

  async update(id: string, input: UserUpdateInput): Promise<UserSummary> {
    const existing = await this.#users.findById(id);
    if (!existing) throw new NotFoundError("User not found");
    await this.#assertNotOwner(id);

    const updated = await this.#uow.runAudited(
      (user: User) => ({
        action: "user.update" as const,
        targetType: "user",
        targetId: user.id,
        outcome: "SUCCESS" as const,
        before: {
          displayName: existing.displayName,
          status: existing.status,
          timezone: existing.timezone,
        },
        after: { displayName: user.displayName, status: user.status, timezone: user.timezone },
      }),
      (tx) => this.#users.update(tx, id, input),
    );

    return toUserSummary(updated);
  }

  /** Owner intervention on a brute-force lockout (§6.3 step 2, FR-029). */
  async clearLockout(id: string): Promise<void> {
    const user = await this.#users.findById(id);
    if (!user) throw new NotFoundError("User not found");

    await this.#logins.clearLockout(user.email);
    await this.#uow.recordOutOfBand({
      action: "user.lockout.clear",
      targetType: "user",
      targetId: user.id,
      outcome: "SUCCESS",
      after: { cleared: true },
    });
  }

  listSessions(userId: string) {
    return this.#sessions.listForUser(userId);
  }

  /** Bulk revoke — takes effect on the very next request of each session (ET-1 1.11). */
  async revokeSessions(userId: string, reason: SessionRevokeReason = "admin_revoke"): Promise<number> {
    const user = await this.#users.findById(userId);
    if (!user) throw new NotFoundError("User not found");

    return this.#uow.runAudited(
      (count: number) => ({
        action: "auth.session.revoke" as const,
        targetType: "user",
        targetId: userId,
        outcome: "SUCCESS" as const,
        after: { revoked: count, reason },
      }),
      async (tx) => {
        const result = await this.#sessions.revokeAllForUser(tx, userId, reason);
        return result.count;
      },
    );
  }

  /**
   * Self-service password change (§6.2, FR-030). Revokes every OTHER session of the user —
   * the caller keeps the one they are using — and the audit record carries the event only,
   * never the value.
   */
  async changeOwnPassword(args: {
    userId: string;
    sessionId: string;
    currentPassword: string;
    newPassword: string;
  }): Promise<void> {
    const user = await this.#users.findById(args.userId);
    if (!user) throw new NotFoundError("User not found");

    if (!(await verifyPassword(user.passwordHash, args.currentPassword))) {
      await this.#denials.record({
        action: "auth.password.change",
        denialReason: "unauthenticated",
        targetType: "user",
        targetId: user.id,
      });
      throw new UnauthenticatedError("Invalid credentials");
    }

    const passwordHash = await hashPassword(args.newPassword);

    await this.#uow.runAudited(
      (revoked: number) => ({
        action: "auth.password.change" as const,
        targetType: "user",
        targetId: user.id,
        outcome: "SUCCESS" as const,
        after: { otherSessionsRevoked: revoked },
      }),
      async (tx) => {
        await this.#users.update(tx, user.id, { passwordHash });
        const result = await this.#sessions.revokeAllForUser(
          tx,
          user.id,
          "password_change",
          args.sessionId,
        );
        return result.count;
      },
    );
  }
}
