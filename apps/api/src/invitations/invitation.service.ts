/**
 * Invitation-only account creation (Gate 1, FR-020/FR-021, ET-1 1.7/1.8).
 *
 * Public registration does not exist — not "is disabled", does not exist: there is no
 * handler, nothing in OpenAPI, and no code path that creates a user without a live
 * invitation row. The only way an account comes into being in Phase 1 is bootstrap (the
 * single owner) or this service.
 *
 * The link is rendered for the owner to convey manually because Phase 1 has no mail
 * transport (Gate 1). The raw token is returned EXACTLY once, at creation; the row stores
 * only `sha256(token)`.
 *
 * Consumed, expired, revoked and mutated tokens all produce the SAME generic failure. A
 * caller cannot distinguish "this token was already used" from "this token never existed"
 * (FR-021, ET-1 1.8) — that is deliberate: token-state disclosure is an enumeration oracle.
 */
import {
  ConflictError,
  InvariantViolationError,
  NotFoundError,
  OWNER_ROLE_ID,
  ValidationError,
  type UserSummary,
} from "@sunil/core";
import { hashPassword, type SunilPrismaClient, type User, type UserRepository } from "@sunil/db";
import { randomToken, sha256Hex } from "../common/crypto.js";
import type { ApiConfig } from "../config/api-config.js";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import type { DenialRecorder } from "../audit/denial-recorder.js";
import { toUserSummary } from "../users/user.service.js";

export interface CreatedInvitation {
  readonly id: string;
  readonly email: string;
  readonly roleId: string;
  readonly expiresAt: Date;
  /** Single-use link token — returned once, for manual conveyance (Gate 1). */
  readonly token: string;
}

/** The invitation row shape this service works with. `@sunil/db` exports no `Invitation` type. */
interface InvitationRow {
  readonly id: string;
  readonly email: string;
  readonly roleId: string;
  readonly expiresAt: Date;
}

export interface InvitationSummary {
  readonly id: string;
  readonly email: string;
  readonly roleId: string;
  readonly expiresAt: Date;
  readonly consumedAt: Date | null;
  readonly revokedAt: Date | null;
  readonly createdAt: Date;
}

export class InvitationService {
  readonly #prisma: SunilPrismaClient;
  readonly #users: UserRepository;
  readonly #uow: AuditedUnitOfWork;
  readonly #denials: DenialRecorder;
  readonly #config: ApiConfig;

  constructor(
    prisma: SunilPrismaClient,
    users: UserRepository,
    uow: AuditedUnitOfWork,
    denials: DenialRecorder,
    config: ApiConfig,
  ) {
    this.#prisma = prisma;
    this.#users = users;
    this.#uow = uow;
    this.#denials = denials;
    this.#config = config;
  }

  async create(args: {
    email: string;
    roleId: string;
    invitedById: string;
  }): Promise<CreatedInvitation> {
    if (args.roleId === OWNER_ROLE_ID) {
      // ADR-001 layer (b): the owner role is never invitable. Exactly one owner exists and
      // it is created by bootstrap.
      throw new InvariantViolationError("The owner role cannot be invited");
    }
    const role = await this.#prisma.role.findUnique({ where: { id: args.roleId } });
    if (!role) throw new NotFoundError("Unknown role");

    const existingUser = await this.#users.findByEmail(args.email);
    if (existingUser) throw new ConflictError("An account already exists for this address");

    const token = randomToken(32);
    const expiresAt = new Date(Date.now() + this.#config.inviteTtlHours * 3_600_000);

    const invitation = await this.#uow.runAudited<InvitationRow>(
      (created) => ({
        action: "invitation.create" as const,
        targetType: "invitation",
        targetId: created.id,
        outcome: "SUCCESS" as const,
        // The email and role, never the token (which is credential material).
        after: { email: args.email, roleId: args.roleId, expiresAt: expiresAt.toISOString() },
      }),
      (tx) =>
        tx.invitation.create({
          data: {
            email: args.email,
            tokenHash: sha256Hex(token),
            roleId: args.roleId,
            invitedById: args.invitedById,
            expiresAt,
          },
        }),
    );

    return {
      id: invitation.id,
      email: invitation.email,
      roleId: invitation.roleId,
      expiresAt: invitation.expiresAt,
      token,
    };
  }

  async listPending(): Promise<InvitationSummary[]> {
    const rows = await this.#prisma.invitation.findMany({
      where: { consumedAt: null, revokedAt: null },
      orderBy: { createdAt: "desc" },
    });
    return rows.map((row) => ({
      id: row.id,
      email: row.email,
      roleId: row.roleId,
      expiresAt: row.expiresAt,
      consumedAt: row.consumedAt,
      revokedAt: row.revokedAt,
      createdAt: row.createdAt,
    }));
  }

  async revoke(id: string): Promise<void> {
    const existing = await this.#prisma.invitation.findUnique({ where: { id } });
    if (!existing || existing.consumedAt || existing.revokedAt) {
      throw new NotFoundError("Invitation not found");
    }

    await this.#uow.runAudited(
      {
        action: "invitation.revoke" as const,
        targetType: "invitation",
        targetId: id,
        outcome: "SUCCESS" as const,
        after: { email: existing.email },
      },
      (tx) => tx.invitation.update({ where: { id }, data: { revokedAt: new Date() } }),
    );
  }

  /**
   * Acceptance. The consumption is a conditional update inside the transaction
   * (`consumedAt IS NULL`), so two simultaneous acceptances of one token cannot both create
   * a user — the loser's update affects zero rows and the whole transaction rolls back.
   */
  async accept(args: {
    token: string;
    password: string;
    displayName?: string;
  }): Promise<UserSummary> {
    const invitation = await this.#prisma.invitation.findUnique({
      where: { tokenHash: sha256Hex(args.token) },
    });

    const now = new Date();
    const usable =
      invitation !== null &&
      invitation.consumedAt === null &&
      invitation.revokedAt === null &&
      invitation.expiresAt > now;

    if (!invitation || !usable) {
      await this.#denials.record({
        action: "invitation.accept",
        denialReason: "validation",
        targetType: "invitation",
        targetId: invitation?.id ?? null,
      });
      // One generic failure for consumed / expired / revoked / never-existed (ET-1 1.8).
      throw new ValidationError("Invitation is not valid", ["token"]);
    }

    const existingUser = await this.#users.findByEmail(invitation.email);
    if (existingUser) {
      await this.#denials.record({
        action: "invitation.accept",
        denialReason: "validation",
        targetType: "invitation",
        targetId: invitation.id,
      });
      throw new ValidationError("Invitation is not valid", ["token"]);
    }

    const passwordHash = await hashPassword(args.password);

    const user = await this.#uow.runAudited<User>(
      (created) => [
        {
          action: "invitation.accept" as const,
          targetType: "invitation",
          targetId: invitation.id,
          outcome: "SUCCESS" as const,
          after: { email: invitation.email, userId: created.id },
          actorOverride: {
            actorType: "HUMAN" as const,
            actorId: created.id,
            actorLabel: created.email,
          },
        },
        {
          action: "user.create" as const,
          targetType: "user",
          targetId: created.id,
          outcome: "SUCCESS" as const,
          after: { email: created.email, roleId: invitation.roleId },
          actorOverride: {
            actorType: "HUMAN" as const,
            actorId: created.id,
            actorLabel: created.email,
          },
        },
      ],
      async (tx) => {
        const consumed = await tx.invitation.updateMany({
          where: { id: invitation.id, consumedAt: null, revokedAt: null },
          data: { consumedAt: now },
        });
        if (consumed.count !== 1) throw new ValidationError("Invitation is not valid", ["token"]);

        const created = await tx.user.create({
          data: {
            email: invitation.email,
            passwordHash,
            displayName: args.displayName ?? invitation.email,
            status: "ACTIVE",
            timezone: this.#config.timezone,
          },
        });

        // Exactly the invited role, and nothing else (ET-1 1.7).
        await tx.userRole.create({
          data: {
            userId: created.id,
            roleId: invitation.roleId,
            assignedById: invitation.invitedById,
          },
        });

        return created;
      },
    );

    return toUserSummary(user);
  }
}
