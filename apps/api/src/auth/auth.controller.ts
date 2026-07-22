/**
 * `/api/auth` — the §13 authentication surface.
 *
 * Every handler carries exactly one §7.4 declaration and every mutating handler carries an
 * `@Audited` action. `/auth/login` and `/auth/mfa/verify` are the only `@Public()` mutating
 * routes in this controller, and both are `@AuthEndpoint()` — the per-IP brute-force ceiling
 * applies before a session exists.
 *
 * There is no registration handler here, or anywhere. FR-020 is satisfied by absence.
 */
import {
  Body,
  Controller,
  Delete,
  Get,
  HttpCode,
  Inject,
  Param,
  Post,
  Res,
} from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import {
  ForbiddenError,
  InvitationAcceptSchema,
  LoginRequestSchema,
  MfaVerifyRequestSchema,
  NotFoundError,
  PasswordChangeRequestSchema,
  UnauthenticatedError,
  type UserSummary,
} from "@sunil/core";
import type { RoleRepository } from "@sunil/db";
import type { HttpReplyLike } from "../common/http.types.js";
import {
  serializeClearedSessionCookie,
  serializeSessionCookie,
} from "../common/cookies.js";
import { Audited, AuthEndpoint, Public, SelfService } from "../common/declarations.js";
import { currentContext } from "../common/request-context.js";
import { parseInput } from "../common/validation.js";
import type { ApiConfig } from "../config/api-config.js";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import type { PermissionService } from "../rbac/permission.service.js";
import type { UserService } from "../users/user.service.js";
import { TOKENS } from "../tokens.js";
import type { LoginService } from "./login.service.js";
import type { MfaService } from "./mfa.service.js";
import type { SessionService } from "./session.service.js";
import type { IssuedSession, SessionUser } from "./session.types.js";

function summaryOf(user: SessionUser): UserSummary {
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

@ApiTags("auth")
@Controller("auth")
export class AuthController {
  constructor(
    @Inject(TOKENS.LoginService) private readonly logins: LoginService,
    @Inject(TOKENS.MfaService) private readonly mfa: MfaService,
    @Inject(TOKENS.SessionService) private readonly sessions: SessionService,
    @Inject(TOKENS.PermissionService) private readonly permissions: PermissionService,
    @Inject(TOKENS.UserService) private readonly users: UserService,
    @Inject(TOKENS.RoleRepository) private readonly roles: RoleRepository,
    @Inject(TOKENS.UnitOfWork) private readonly uow: AuditedUnitOfWork,
    @Inject(TOKENS.Config) private readonly config: ApiConfig,
  ) {}

  #setSessionCookie(reply: HttpReplyLike, issued: IssuedSession): void {
    const maxAgeSeconds = Math.floor((issued.absoluteExpiresAt.getTime() - Date.now()) / 1000);
    void reply.header(
      "set-cookie",
      serializeSessionCookie(this.config.cookieName, issued.token, {
        secure: this.config.cookieSecure,
        maxAgeSeconds,
      }),
    );
  }

  @Post("login")
  @Public()
  @AuthEndpoint()
  @Audited("auth.login.success")
  @HttpCode(200)
  @ApiOperation({ summary: "Authenticate with email and password" })
  async login(@Body() body: unknown, @Res({ passthrough: true }) reply: HttpReplyLike) {
    const input = parseInput(LoginRequestSchema, body);
    const context = currentContext();

    const result = await this.logins.login({
      email: input.email,
      password: input.password,
      ip: context?.ip ?? null,
      userAgent: context?.userAgent ?? null,
    });

    this.#setSessionCookie(reply, result.session);

    // The CSRF token is issued here even when MFA is still outstanding, because
    // `/auth/mfa/verify` is itself a mutating request and ADR-009 admits no unprotected
    // mutation. It is not a privilege: a PENDING_MFA session authorises nothing, and both
    // the session token and this secret are ROTATED on elevation (§6.2).
    return {
      user: summaryOf(result.user),
      mfaRequired: result.mfaRequired,
      csrfToken: result.session.csrfSecret,
    };
  }

  @Post("mfa/verify")
  @Public()
  @AuthEndpoint()
  @Audited("auth.mfa.verify.success")
  @HttpCode(200)
  @ApiOperation({ summary: "Complete an MFA challenge and establish the session" })
  async verifyMfa(@Body() body: unknown, @Res({ passthrough: true }) reply: HttpReplyLike) {
    const input = parseInput(MfaVerifyRequestSchema, body);
    const session = currentContext()?.session;
    if (!session || session.state !== "PENDING_MFA") {
      throw new UnauthenticatedError("No MFA challenge in progress");
    }

    const issued = await this.mfa.verifyChallenge({
      sessionId: session.id,
      user: session.user,
      ...(input.code ? { code: input.code } : {}),
      ...(input.recoveryCode ? { recoveryCode: input.recoveryCode } : {}),
    });

    this.#setSessionCookie(reply, issued);
    return { user: summaryOf(session.user), csrfToken: issued.csrfSecret };
  }

  @Post("logout")
  @SelfService()
  @Audited("auth.logout")
  @HttpCode(200)
  async logout(@Res({ passthrough: true }) reply: HttpReplyLike) {
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");

    await this.uow.runAudited(
      {
        action: "auth.logout",
        targetType: "session",
        targetId: session.id,
        outcome: "SUCCESS",
      },
      (tx) => this.sessions.revoke(tx, session.id, "logout"),
    );

    void reply.header(
      "set-cookie",
      serializeClearedSessionCookie(this.config.cookieName, this.config.cookieSecure),
    );
    return { ok: true };
  }

  @Get("me")
  @SelfService()
  @ApiOperation({ summary: "The caller's identity, roles, permissions and CSRF token" })
  async me() {
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");

    const [permissions, allRoles, assignments] = await Promise.all([
      this.permissions.resolve(session.userId),
      this.roles.listAll(),
      this.users.roleIdsFor(session.userId),
    ]);
    const held = new Set(assignments.map((row) => row.roleId));

    return {
      user: summaryOf(session.user),
      roles: allRoles
        .filter((role) => held.has(role.id))
        .map((role) => ({
          id: role.id,
          slug: role.slug,
          name: role.name,
          description: role.description,
          isSystem: role.isSystem,
        })),
      permissions,
      csrfToken: session.csrfSecret,
    };
  }

  @Get("sessions")
  @SelfService()
  async ownSessions() {
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");
    const rows = await this.sessions.listForUser(session.userId);
    return { items: rows.map(sessionSummary) };
  }

  @Delete("sessions/:id")
  @SelfService()
  @Audited("auth.session.revoke")
  @HttpCode(200)
  async revokeOwnSession(@Param("id") id: string) {
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");

    const target = await this.sessions.findById(id);
    // Self-service acts only on the caller's own account (§7.4). A session belonging to
    // someone else is reported as not found — not as forbidden — so this endpoint cannot be
    // used to test whether a session id exists.
    if (!target || target.userId !== session.userId) throw new NotFoundError("Session not found");

    await this.uow.runAudited(
      {
        action: "auth.session.revoke",
        targetType: "session",
        targetId: id,
        outcome: "SUCCESS",
        after: { reason: "logout" },
      },
      (tx) => this.sessions.revoke(tx, id, "logout"),
    );
    return { ok: true };
  }

  @Post("password")
  @SelfService()
  @Audited("auth.password.change")
  @HttpCode(200)
  async changePassword(@Body() body: unknown) {
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");
    const input = parseInput(PasswordChangeRequestSchema, body);

    await this.users.changeOwnPassword({
      userId: session.userId,
      sessionId: session.id,
      currentPassword: input.currentPassword,
      newPassword: input.newPassword,
    });
    return { ok: true };
  }

  @Post("mfa/enrol")
  @SelfService()
  @Audited("auth.mfa.enrol")
  @HttpCode(200)
  @ApiOperation({
    summary: "Begin TOTP enrolment. Returns the otpauth URI and secret exactly once.",
  })
  async enrolMfa() {
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");
    return this.mfa.enrol(session.user);
  }

  @Post("mfa/activate")
  @SelfService()
  @Audited("auth.mfa.activate")
  @HttpCode(200)
  async activateMfa(@Body() body: unknown) {
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");
    const input = parseInput(MfaVerifyRequestSchema, body);
    if (!input.code) throw new ForbiddenError("A TOTP code is required to activate");
    const recoveryCodes = await this.mfa.activate(session.user, input.code);
    return { recoveryCodes };
  }

  @Post("mfa/disable")
  @SelfService()
  @Audited("auth.mfa.disable")
  @HttpCode(200)
  async disableMfa(@Body() body: unknown) {
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");
    const input = parseInput(InvitationAcceptSchema.pick({ password: true }), body);
    await this.mfa.disable(session.user, input.password);
    return { ok: true };
  }
}

function sessionSummary(row: {
  id: string;
  state: string;
  createdAt: Date;
  lastSeenAt: Date;
  idleExpiresAt: Date;
  absoluteExpiresAt: Date;
  revokedAt: Date | null;
  revokedReason: string | null;
  ip: string | null;
  userAgent: string | null;
}) {
  return {
    id: row.id,
    state: row.state,
    createdAt: row.createdAt,
    lastSeenAt: row.lastSeenAt,
    idleExpiresAt: row.idleExpiresAt,
    absoluteExpiresAt: row.absoluteExpiresAt,
    revokedAt: row.revokedAt,
    revokedReason: row.revokedReason,
    ip: row.ip,
    userAgent: row.userAgent,
  };
}
