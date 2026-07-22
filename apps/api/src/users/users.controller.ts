/** `/api/users` — the §13 permission-guarded user surface. */
import { Body, Controller, Get, HttpCode, Inject, Param, Patch, Post, Put } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import {
  PageRequestSchema,
  RoleAssignmentSchema,
  UserUpdateSchema,
  UuidSchema,
} from "@sunil/core";
import { Audited, RequiresPermission } from "../common/declarations.js";
import { parseInput } from "../common/validation.js";
import { TOKENS } from "../tokens.js";
import type { RoleAssignmentService } from "../rbac/role-assignment.service.js";
import type { UserService } from "./user.service.js";

@ApiTags("users")
@Controller("users")
export class UsersController {
  constructor(
    @Inject(TOKENS.UserService) private readonly users: UserService,
    @Inject(TOKENS.RoleAssignmentService) private readonly roleAssignment: RoleAssignmentService,
  ) {}

  @Get()
  @RequiresPermission("user:read")
  list(@Body() _body: unknown, @Param() _params: unknown) {
    return this.users.list({ page: 1, pageSize: 50 });
  }

  @Get(":id")
  @RequiresPermission("user:read")
  get(@Param("id") id: string) {
    return this.users.get(parseInput(UuidSchema, id));
  }

  @Patch(":id")
  @RequiresPermission("user:update")
  @Audited("user.update")
  update(@Param("id") id: string, @Body() body: unknown) {
    return this.users.update(parseInput(UuidSchema, id), parseInput(UserUpdateSchema, body));
  }

  @Post(":id/lockout/clear")
  @RequiresPermission("user:update")
  @Audited("user.lockout.clear")
  @HttpCode(200)
  @ApiOperation({ summary: "Clear a brute-force lockout for an account (FR-029)" })
  async clearLockout(@Param("id") id: string) {
    await this.users.clearLockout(parseInput(UuidSchema, id));
    return { ok: true };
  }

  /**
   * The §6.6 choke point. Everything interesting happens inside
   * `RoleAssignmentService.changeRoles`: before/after permission sets, the audit record and
   * — on any privilege REDUCTION — revocation of that user's sessions, all in one
   * transaction.
   */
  @Put(":id/roles")
  @RequiresPermission("role:assign")
  @Audited("user.role.change")
  @ApiOperation({ summary: "Replace a user's roles (privilege reduction revokes sessions)" })
  changeRoles(@Param("id") id: string, @Body() body: unknown) {
    const input = parseInput(RoleAssignmentSchema, body);
    return this.roleAssignment.changeRoles(parseInput(UuidSchema, id), input.roleIds);
  }

  @Get(":id/sessions")
  @RequiresPermission("session:read")
  async sessions(@Param("id") id: string) {
    const rows = await this.users.listSessions(parseInput(UuidSchema, id));
    return { items: rows };
  }

  @Post(":id/sessions/revoke")
  @RequiresPermission("session:revoke")
  @Audited("auth.session.revoke")
  @HttpCode(200)
  @ApiOperation({ summary: "Revoke every session for a user (effective on the next request)" })
  async revokeSessions(@Param("id") id: string) {
    const revoked = await this.users.revokeSessions(parseInput(UuidSchema, id));
    return { revoked };
  }
}

/** Exported so the pagination schema stays a single definition if this list grows filters. */
export const USERS_PAGE_SCHEMA = PageRequestSchema;
