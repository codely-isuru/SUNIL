/**
 * Idempotent bootstrap (§5.8, FR-014, ADR-001).
 *
 * Seeds: the 4 system roles with fixed UUIDs, the 21 permissions, the role↔permission
 * grants, the 3 disabled/UNCONFIGURED LLM provider rows, the seed system settings, and
 * EXACTLY ONE owner.
 *
 * Idempotence contract: a second run creates no duplicate role, permission, provider,
 * setting or owner, and exits 0.
 *
 * Owner credentials come from `SUNIL_OWNER_EMAIL` / `SUNIL_OWNER_INITIAL_PASSWORD` in the
 * environment at bootstrap time. There is NO default and no fallback — a missing variable is
 * a hard failure, because a committed default owner password is exactly what FR-014 forbids.
 *
 * MAINTENANCE NOTE (ADR-001 consequence): re-run this seed whenever the permission
 * catalogue in `@sunil/core` grows. Forgetting leaves the owner without the new permission,
 * which fails closed and is visible — but it still needs doing.
 */
import { randomUUID } from "node:crypto";
import type { Prisma } from "@prisma/client";
import {
  BootstrapEnvSchema,
  ConfigurationError,
  EmailSchema,
  OWNER_ROLE_ID,
  PasswordSchema,
  PERMISSIONS,
  PERMISSION_DESCRIPTIONS,
  SEED_ROLES,
  parseEnv,
  type AuditEntry,
} from "@sunil/core";
import type { SunilPrismaClient, TransactionClient } from "../client.js";
import type { UnitOfWork } from "../unit-of-work.js";
import { hashPassword } from "../password.js";

export interface BootstrapReport {
  readonly correlationId: string;
  readonly rolesUpserted: number;
  readonly permissionsUpserted: number;
  readonly grantsCreated: number;
  readonly grantsRevoked: number;
  readonly providersCreated: number;
  readonly settingsCreated: number;
  readonly ownerCreated: boolean;
  readonly ownerEmail: string;
}

const SYSTEM_ACTOR = {
  actorType: "SYSTEM",
  actorLabel: "system:bootstrap",
} as const;

function systemAudit(
  correlationId: string,
  targetType: string,
  after: Record<string, unknown>,
): AuditEntry {
  return {
    ...SYSTEM_ACTOR,
    action: "system.bootstrap",
    targetType,
    outcome: "SUCCESS",
    correlationId,
    after,
  };
}

/** Provider rows are created DISABLED and UNCONFIGURED. Phase 1 never reaches LIVE_VERIFIED. */
const SEED_PROVIDERS = [
  { slug: "anthropic", name: "Anthropic", baseUrl: null, defaultModel: null },
  { slug: "openai", name: "OpenAI", baseUrl: null, defaultModel: null },
  { slug: "ollama", name: "Ollama (local)", baseUrl: null, defaultModel: null },
] as const;

/**
 * Seed settings. `llm.modelRates` starts EMPTY on purpose: cost estimation reads rates from
 * this row (FR-064), and shipping invented prices would be worse than shipping none.
 */
const SEED_SETTINGS: readonly {
  key: string;
  value: Prisma.InputJsonValue;
  valueType: string;
  description: string;
}[] = [
  {
    key: "llm.modelRates",
    value: {},
    valueType: "json",
    description:
      "Per-model token rates used for cost estimation. Shape: { \"<model>\": { inputPerMillionUsd, outputPerMillionUsd } }. Empty until an operator supplies rates.",
  },
  {
    key: "platform.displayName",
    value: "SUNIL",
    valueType: "string",
    description: "Name shown in the portal shell.",
  },
  {
    key: "phase.limitations",
    value: {
      llmAdaptersVerification: "mock-verified only — unverified against live endpoints",
      approvalWorkflow: "APPROVAL_REQUIRED envelopes persist; no approval workflow exists",
      toolUse: "agent tool allowlists must be empty in Phase 1",
    },
    valueType: "json",
    description:
      "Machine-readable statement of Phase 1 limitations, rendered by the portal (NFR-019).",
  },
];

export interface BootstrapDeps {
  readonly prisma: SunilPrismaClient;
  readonly uow: UnitOfWork;
  readonly env?: NodeJS.ProcessEnv;
}

export async function bootstrap(deps: BootstrapDeps): Promise<BootstrapReport> {
  const env = parseEnv(BootstrapEnvSchema, deps.env ?? process.env);
  const ownerEmail = EmailSchema.parse(env.SUNIL_OWNER_EMAIL);
  const correlationId = `bootstrap-${randomUUID()}`;

  // The owner's initial credential is held to the same policy as every other password
  // (FR-030). The failure message names the variable and its policy violation — never the
  // submitted value.
  const passwordCheck = PasswordSchema.safeParse(env.SUNIL_OWNER_INITIAL_PASSWORD);
  if (!passwordCheck.success) {
    throw new ConfigurationError(
      `SUNIL_OWNER_INITIAL_PASSWORD ${passwordCheck.error.issues.map((i) => i.message).join("; ")}`,
      ["SUNIL_OWNER_INITIAL_PASSWORD"],
    );
  }

  const roleResult = await seedRolesAndPermissions(deps, correlationId);
  const providersCreated = await seedProviders(deps, correlationId);
  const settingsCreated = await seedSettings(deps, correlationId);
  const ownerCreated = await seedOwner(
    deps,
    correlationId,
    ownerEmail,
    env.SUNIL_OWNER_INITIAL_PASSWORD,
    env.SUNIL_TIMEZONE,
  );

  return {
    correlationId,
    ...roleResult,
    providersCreated,
    settingsCreated,
    ownerCreated,
    ownerEmail,
  };
}

async function seedRolesAndPermissions(
  deps: BootstrapDeps,
  correlationId: string,
): Promise<{
  rolesUpserted: number;
  permissionsUpserted: number;
  grantsCreated: number;
  grantsRevoked: number;
}> {
  return deps.uow.runAudited<{
    rolesUpserted: number;
    permissionsUpserted: number;
    grantsCreated: number;
    grantsRevoked: number;
  }>(
    (result) =>
      systemAudit(correlationId, "rbac", {
        roles: result.rolesUpserted,
        permissions: result.permissionsUpserted,
        grantsCreated: result.grantsCreated,
        grantsRevoked: result.grantsRevoked,
      }),
    async (tx: TransactionClient) => {
      for (const role of SEED_ROLES) {
        await tx.role.upsert({
          where: { id: role.id },
          create: {
            id: role.id,
            slug: role.slug,
            name: role.name,
            description: role.description,
            isSystem: true,
          },
          update: { slug: role.slug, name: role.name, description: role.description, isSystem: true },
        });
      }

      for (const key of PERMISSIONS) {
        await tx.permission.upsert({
          where: { key },
          create: { key, description: PERMISSION_DESCRIPTIONS[key] },
          update: { description: PERMISSION_DESCRIPTIONS[key] },
        });
      }

      const permissionRows = await tx.permission.findMany({ select: { id: true, key: true } });
      const idByKey = new Map(permissionRows.map((row) => [row.key, row.id]));

      let grantsCreated = 0;
      let grantsRevoked = 0;

      for (const role of SEED_ROLES) {
        const wantedIds = role.permissions
          .map((key) => idByKey.get(key))
          .filter((id): id is string => typeof id === "string");

        // The seed is AUTHORITATIVE for system roles: grants not in the definition are
        // removed, so a role cannot silently retain a permission it was once given.
        const revoked = await tx.rolePermission.deleteMany({
          where: { roleId: role.id, permissionId: { notIn: wantedIds.length ? wantedIds : [""] } },
        });
        grantsRevoked += revoked.count;

        const created = await tx.rolePermission.createMany({
          data: wantedIds.map((permissionId) => ({ roleId: role.id, permissionId })),
          skipDuplicates: true,
        });
        grantsCreated += created.count;
      }

      return {
        rolesUpserted: SEED_ROLES.length,
        permissionsUpserted: PERMISSIONS.length,
        grantsCreated,
        grantsRevoked,
      };
    },
  );
}

async function seedProviders(deps: BootstrapDeps, correlationId: string): Promise<number> {
  return deps.uow.runAudited<number>(
    (created) => systemAudit(correlationId, "llm_provider", { created }),
    async (tx) => {
      let created = 0;
      for (const provider of SEED_PROVIDERS) {
        const existing = await tx.llmProvider.findUnique({ where: { slug: provider.slug } });
        if (existing) continue;
        await tx.llmProvider.create({
          data: {
            slug: provider.slug,
            name: provider.name,
            baseUrl: provider.baseUrl,
            defaultModel: provider.defaultModel,
            enabled: false,
            verificationStatus: "UNCONFIGURED",
          },
        });
        created += 1;
      }
      return created;
    },
  );
}

async function seedSettings(deps: BootstrapDeps, correlationId: string): Promise<number> {
  return deps.uow.runAudited<number>(
    (created) => systemAudit(correlationId, "system_setting", { created }),
    async (tx) => {
      let created = 0;
      for (const setting of SEED_SETTINGS) {
        const existing = await tx.systemSetting.findUnique({ where: { key: setting.key } });
        if (existing) continue;
        await tx.systemSetting.create({
          data: {
            key: setting.key,
            value: setting.value,
            valueType: setting.valueType,
            description: setting.description,
          },
        });
        created += 1;
      }
      return created;
    },
  );
}

/**
 * Exactly one owner (ADR-001 layer (a)). If an owner assignment already exists this changes
 * nothing — it does not reset the password, rename the account or create a second owner.
 * Layer (c), the `one_owner_only` partial unique index, rejects a second assignment at the
 * database even if this check were bypassed.
 */
async function seedOwner(
  deps: BootstrapDeps,
  correlationId: string,
  ownerEmail: string,
  initialPassword: string,
  timezone: string,
): Promise<boolean> {
  const existingOwner = await deps.prisma.userRole.count({ where: { roleId: OWNER_ROLE_ID } });
  if (existingOwner > 0) return false;

  const passwordHash = await hashPassword(initialPassword);

  return deps.uow.runAudited<boolean>(
    systemAudit(correlationId, "user", {
      email: ownerEmail,
      role: "owner",
      note: "initial owner created from environment-supplied credentials",
    }),
    async (tx) => {
      const user = await tx.user.upsert({
        where: { email: ownerEmail },
        create: {
          email: ownerEmail,
          passwordHash,
          displayName: "Owner",
          status: "ACTIVE",
          timezone,
        },
        update: {},
      });

      await tx.userRole.create({
        data: { userId: user.id, roleId: OWNER_ROLE_ID, assignedById: null },
      });

      return true;
    },
  );
}
