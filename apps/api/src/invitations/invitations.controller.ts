/**
 * `/api/invitations` — invitation-only account creation (§13, Gate 1).
 *
 * `POST /invitations` returns the single-use LINK in the response for the owner to convey
 * manually. That is the Gate-1 decision, not an oversight: Phase 1 has no mail transport and
 * SECURITY_MODEL §10 forbids real outbound mail in development.
 */
import { Body, Controller, Delete, Get, HttpCode, Inject, Param, Post } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import { InvitationAcceptSchema, InvitationCreateSchema, UuidSchema } from "@sunil/core";
import {
  Audited,
  AuthEndpoint,
  Idempotent,
  Public,
  RequiresPermission,
} from "../common/declarations.js";
import { currentContext } from "../common/request-context.js";
import { parseInput } from "../common/validation.js";
import { UnauthenticatedError } from "@sunil/core";
import { TOKENS } from "../tokens.js";
import type { InvitationService } from "./invitation.service.js";

@ApiTags("invitations")
@Controller("invitations")
export class InvitationsController {
  constructor(@Inject(TOKENS.InvitationService) private readonly invitations: InvitationService) {}

  @Post()
  @RequiresPermission("user:invite")
  @Audited("invitation.create")
  @Idempotent()
  @ApiOperation({ summary: "Create an invitation and render its single-use link" })
  async create(@Body() body: unknown) {
    const input = parseInput(InvitationCreateSchema, body);
    const session = currentContext()?.session;
    if (!session) throw new UnauthenticatedError("No session");

    const created = await this.invitations.create({
      email: input.email,
      roleId: input.roleId,
      invitedById: session.userId,
    });

    return {
      id: created.id,
      email: created.email,
      roleId: created.roleId,
      expiresAt: created.expiresAt,
      // Shown once, conveyed manually (Gate 1).
      acceptPath: `/api/invitations/${created.token}/accept`,
      token: created.token,
    };
  }

  @Get()
  @RequiresPermission("user:invite")
  async list() {
    return { items: await this.invitations.listPending() };
  }

  @Delete(":id")
  @RequiresPermission("user:invite")
  @Audited("invitation.revoke")
  @HttpCode(200)
  async revoke(@Param("id") id: string) {
    await this.invitations.revoke(parseInput(UuidSchema, id));
    return { ok: true };
  }

  /**
   * The one public write path that creates a user. Consumed, expired, revoked and mutated
   * tokens all produce the same generic 400 (ET-1 1.8).
   */
  @Post(":token/accept")
  @Public()
  @AuthEndpoint()
  @Audited("invitation.accept")
  @HttpCode(201)
  async accept(@Param("token") token: string, @Body() body: unknown) {
    const input = parseInput(InvitationAcceptSchema, body);
    await this.invitations.accept({
      token,
      password: input.password,
      ...(input.displayName ? { displayName: input.displayName } : {}),
    });
    return { ok: true };
  }
}
