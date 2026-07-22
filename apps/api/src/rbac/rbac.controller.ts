/**
 * `/api/roles` and `/api/permissions` (§13).
 *
 * Both are `role:read`. The permission catalogue is served from the DATABASE, not from the
 * `@sunil/core` constant, because ET-2 2.5 requires that granting a permission in the
 * database changes behaviour with no code change — reading the catalogue from a compiled
 * constant would quietly make that untrue for anything downstream of it.
 */
import { Controller, Get, Inject } from "@nestjs/common";
import { ApiTags } from "@nestjs/swagger";
import type { PermissionRepository, RoleRepository } from "@sunil/db";
import { RequiresPermission } from "../common/declarations.js";
import { TOKENS } from "../tokens.js";

@ApiTags("rbac")
@Controller()
export class RbacController {
  constructor(
    @Inject(TOKENS.RoleRepository) private readonly roles: RoleRepository,
    @Inject(TOKENS.PermissionRepository) private readonly permissions: PermissionRepository,
  ) {}

  @Get("roles")
  @RequiresPermission("role:read")
  async listRoles() {
    const rows = await this.roles.listAll();
    return {
      items: await Promise.all(
        rows.map(async (role) => ({
          id: role.id,
          slug: role.slug,
          name: role.name,
          description: role.description,
          isSystem: role.isSystem,
          permissions: await this.roles.listPermissionKeys(role.id),
        })),
      ),
    };
  }

  @Get("permissions")
  @RequiresPermission("role:read")
  async listPermissions() {
    return { items: await this.permissions.listAll() };
  }
}
