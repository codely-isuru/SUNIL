/**
 * Permission catalogue and seed-role definitions — ADR-001, PHASE1_ARCHITECTURE §7.1/§7.2.
 *
 * Rules that are structural, not stylistic:
 *  - Flat, lowercase `resource:action` strings. There is NO wildcard grammar at runtime;
 *    the guard is a set-membership test, so it cannot be wrong in an interesting way.
 *  - New permission strings are an architect-reviewed addition to THIS file (risk R-08).
 *  - `owner` is re-granted *all known permissions* by the idempotent seed on every run,
 *    so permissions added in later phases flow to the owner without a matcher.
 */
import { z } from "./zod.js";
import type { RoleSlug } from "./types.js";

/** The complete Phase 1 catalogue: 21 concrete permissions. */
export const PERMISSIONS = [
  "user:read",
  "user:invite",
  "user:update",
  "role:read",
  "role:assign",
  "session:read",
  "session:revoke",
  "secret:create",
  "secret:read",
  "secret:rotate",
  "secret:delete",
  "settings:read",
  "settings:write",
  "provider:read",
  "provider:write",
  "audit:read",
  "usage:read",
  "agent:read",
  "agent:write",
  "job:read",
  "dashboard:read",
] as const;

export type PermissionKey = (typeof PERMISSIONS)[number];

export const PermissionKeySchema = z.enum(PERMISSIONS);

/**
 * Descriptions are seeded into `permissions.description` so the portal can render the
 * catalogue without a second source of truth.
 *
 * `secret:read` deliberately grants METADATA reads only — no permission string exists
 * that returns a secret value, because no API returns one (§8.4).
 */
export const PERMISSION_DESCRIPTIONS: Readonly<Record<PermissionKey, string>> = {
  "user:read": "List and view user accounts (never password hashes).",
  "user:invite": "Create and revoke invitations to the platform.",
  "user:update": "Update user profile fields, status and clear login lockouts.",
  "role:read": "List roles and the permission catalogue.",
  "role:assign": "Change the roles assigned to a user.",
  "session:read": "View sessions belonging to any user.",
  "session:revoke": "Revoke sessions belonging to any user.",
  "secret:create": "Store a new secret in the SecretStore.",
  "secret:read": "Read secret METADATA and fingerprints only — never a secret value.",
  "secret:rotate": "Replace the value behind an existing secret reference.",
  "secret:delete": "Delete a secret that nothing references.",
  "settings:read": "Read system settings.",
  "settings:write": "Change system settings.",
  "provider:read": "Read LLM provider configuration (credential references only).",
  "provider:write": "Change LLM provider configuration.",
  "audit:read": "Query the append-only audit log.",
  "usage:read": "Query LLM usage records.",
  "agent:read": "View agents and their activity envelopes.",
  "agent:write": "Create, configure and run agents.",
  "job:read": "View queue status and job execution history.",
  "dashboard:read": "View the dashboard shell.",
};

/**
 * Deterministic system-role UUIDs (UUIDv7 shape). Fixed so that migrations and the
 * `one_owner_only` partial unique index can reference the owner role literally.
 * Re-keying a system role is deliberately a migration-level change (ADR-001).
 */
export const ROLE_IDS = {
  owner: "00000000-0000-7000-8000-000000000001",
  admin: "00000000-0000-7000-8000-000000000002",
  viewer: "00000000-0000-7000-8000-000000000003",
  agent: "00000000-0000-7000-8000-000000000004",
} as const satisfies Record<RoleSlug, string>;

export const OWNER_ROLE_ID = ROLE_IDS.owner;

export const ROLE_SLUGS = ["owner", "admin", "viewer", "agent"] as const;
export const RoleSlugSchema = z.enum(ROLE_SLUGS);

export interface SeedRoleDefinition {
  readonly id: string;
  readonly slug: RoleSlug;
  readonly name: string;
  readonly description: string;
  readonly isSystem: true;
  readonly permissions: readonly PermissionKey[];
}

/** `admin` holds everything except `role:assign` — role changes are owner-only (§7.2). */
const ADMIN_PERMISSIONS: readonly PermissionKey[] = PERMISSIONS.filter(
  (p): p is PermissionKey => p !== "role:assign",
);

export const SEED_ROLES: readonly SeedRoleDefinition[] = [
  {
    id: ROLE_IDS.owner,
    slug: "owner",
    name: "Owner",
    description:
      "Sole principal. Holds every permission; exactly one holder is enforced at three layers.",
    isSystem: true,
    permissions: PERMISSIONS,
  },
  {
    id: ROLE_IDS.admin,
    slug: "admin",
    name: "Administrator",
    description:
      "Operates the platform. Everything except role assignment; may never target the owner account.",
    isSystem: true,
    permissions: ADMIN_PERMISSIONS,
  },
  {
    id: ROLE_IDS.viewer,
    slug: "viewer",
    name: "Viewer",
    description: "Read-only observer. The default-deny proof persona.",
    isSystem: true,
    permissions: ["dashboard:read", "audit:read"],
  },
  {
    id: ROLE_IDS.agent,
    slug: "agent",
    name: "Agent",
    description:
      "Non-human principal represented for audit only. No portal login path exists for it.",
    isSystem: true,
    permissions: [],
  },
];

/** Set-membership test. This is the entirety of the authorisation algebra (ADR-001). */
export function hasPermission(
  granted: Iterable<string>,
  required: PermissionKey,
): boolean {
  for (const g of granted) {
    if (g === required) return true;
  }
  return false;
}

export function isPermissionKey(value: string): value is PermissionKey {
  return (PERMISSIONS as readonly string[]).includes(value);
}
