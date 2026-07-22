import { describe, expect, it } from "vitest";
import {
  OWNER_ROLE_ID,
  PERMISSIONS,
  PERMISSION_DESCRIPTIONS,
  ROLE_IDS,
  SEED_ROLES,
  hasPermission,
  isPermissionKey,
  type PermissionKey,
} from "../permissions.js";

describe("permission catalogue (ADR-001 / §7.1)", () => {
  it("contains exactly the 21 Phase 1 permissions", () => {
    expect(PERMISSIONS).toHaveLength(21);
  });

  it("has no duplicates", () => {
    expect(new Set(PERMISSIONS).size).toBe(PERMISSIONS.length);
  });

  it("uses flat lowercase resource:action strings with no wildcard grammar", () => {
    for (const key of PERMISSIONS) {
      expect(key).toMatch(/^[a-z][a-z.]*:[a-z][a-z]*$/);
      expect(key).not.toContain("*");
    }
  });

  it("documents every permission", () => {
    for (const key of PERMISSIONS) {
      expect(PERMISSION_DESCRIPTIONS[key]).toBeTruthy();
    }
    expect(Object.keys(PERMISSION_DESCRIPTIONS)).toHaveLength(PERMISSIONS.length);
  });

  it("never exposes a permission that returns a secret value", () => {
    // §8.4: `secret:read` is metadata-only; no value-returning permission may exist.
    expect(PERMISSIONS).not.toContain("secret:value" as PermissionKey);
    expect(PERMISSION_DESCRIPTIONS["secret:read"]).toMatch(/never a secret value/i);
  });
});

describe("seed roles (§7.2)", () => {
  const bySlug = new Map(SEED_ROLES.map((r) => [r.slug, r]));

  it("defines exactly owner, admin, viewer and agent", () => {
    expect([...bySlug.keys()].sort()).toEqual(["admin", "agent", "owner", "viewer"]);
  });

  it("grants the owner every known permission", () => {
    expect([...(bySlug.get("owner")?.permissions ?? [])].sort()).toEqual([...PERMISSIONS].sort());
  });

  it("grants admin everything except role:assign", () => {
    const admin = bySlug.get("admin")?.permissions ?? [];
    expect(admin).not.toContain("role:assign");
    expect(admin).toHaveLength(PERMISSIONS.length - 1);
  });

  it("grants viewer only dashboard:read and audit:read", () => {
    expect([...(bySlug.get("viewer")?.permissions ?? [])].sort()).toEqual([
      "audit:read",
      "dashboard:read",
    ]);
  });

  it("grants the agent principal nothing", () => {
    expect(bySlug.get("agent")?.permissions).toHaveLength(0);
  });

  it("uses fixed, distinct, UUIDv7-shaped system role ids", () => {
    const ids = Object.values(ROLE_IDS);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
    }
    // The partial unique index in the migration hard-codes this literal.
    expect(OWNER_ROLE_ID).toBe("00000000-0000-7000-8000-000000000001");
  });
});

describe("hasPermission — the entire authorisation algebra", () => {
  it("is a set-membership test with no wildcard semantics", () => {
    expect(hasPermission(["user:read", "audit:read"], "user:read")).toBe(true);
    expect(hasPermission(["user:read"], "user:update")).toBe(false);
    expect(hasPermission(["user:*"], "user:update")).toBe(false);
    expect(hasPermission(["*:*"], "user:update")).toBe(false);
    expect(hasPermission([], "dashboard:read")).toBe(false);
  });

  it("recognises only catalogued keys", () => {
    expect(isPermissionKey("user:read")).toBe(true);
    expect(isPermissionKey("user:destroy")).toBe(false);
  });
});
