/** Identity boundary schemas — login, MFA, invitations, users (§13). */
import { z } from "../zod.js";
import { EmailSchema, PasswordSchema, UuidSchema } from "./common.js";
import { RoleSlugSchema } from "../permissions.js";

export const USER_STATUSES = ["ACTIVE", "DISABLED"] as const;
export const UserStatusSchema = z.enum(USER_STATUSES);

export const SESSION_STATES = ["PENDING_MFA", "ACTIVE", "REVOKED"] as const;
export const SessionStateSchema = z.enum(SESSION_STATES);

export const MFA_STATUSES = ["PENDING", "ACTIVE"] as const;
export const MfaStatusSchema = z.enum(MFA_STATUSES);

/** Projection returned by every user-facing endpoint. Carries no hash, ever (FR-011). */
export const UserSummarySchema = z.object({
  id: UuidSchema,
  email: z.string(),
  displayName: z.string(),
  status: UserStatusSchema,
  timezone: z.string(),
  mfaEnabled: z.boolean(),
  createdAt: z.coerce.date(),
});

export const LoginRequestSchema = z.object({
  email: EmailSchema,
  password: z.string().min(1).max(400),
});

export const LoginResponseSchema = z.object({
  user: UserSummarySchema,
  mfaRequired: z.boolean(),
  csrfToken: z.string().optional(),
});

/** Exactly one of `code` / `recoveryCode` (§6.4). */
export const MfaVerifyRequestSchema = z
  .object({
    code: z
      .string()
      .regex(/^\d{6}$/, { message: "must be six digits" })
      .optional(),
    recoveryCode: z
      .string()
      .trim()
      .toUpperCase()
      .regex(/^[A-Z2-7]{10}$/, { message: "must be a 10-character recovery code" })
      .optional(),
  })
  .refine(
    (value) => Boolean(value.code) !== Boolean(value.recoveryCode),
    { message: "provide exactly one of code or recoveryCode" },
  );

export const PasswordChangeRequestSchema = z.object({
  currentPassword: z.string().min(1).max(400),
  newPassword: PasswordSchema,
});

/**
 * Invitations may never name the owner role — a service invariant AND the seed excludes it
 * (ADR-001 layer (b)).
 */
export const InvitationCreateSchema = z.object({
  email: EmailSchema,
  roleId: UuidSchema,
});

export const InvitationAcceptSchema = z.object({
  password: PasswordSchema,
  displayName: z.string().trim().min(1).max(200).optional(),
});

export const UserUpdateSchema = z
  .object({
    displayName: z.string().trim().min(1).max(200).optional(),
    status: UserStatusSchema.optional(),
    timezone: z.string().trim().min(1).max(64).optional(),
  })
  .refine((value) => Object.keys(value).length > 0, {
    message: "at least one field must be supplied",
  });

/** The §6.6 choke point's request shape. */
export const RoleAssignmentSchema = z.object({
  roleIds: z.array(UuidSchema).min(1).max(4),
});

export const RoleSummarySchema = z.object({
  id: UuidSchema,
  slug: RoleSlugSchema,
  name: z.string(),
  description: z.string(),
  isSystem: z.boolean(),
});

export const SessionSummarySchema = z.object({
  id: UuidSchema,
  state: SessionStateSchema,
  createdAt: z.coerce.date(),
  lastSeenAt: z.coerce.date(),
  idleExpiresAt: z.coerce.date(),
  absoluteExpiresAt: z.coerce.date(),
  revokedAt: z.coerce.date().nullish(),
  revokedReason: z.string().nullish(),
  ip: z.string().nullish(),
  userAgent: z.string().nullish(),
});

/** Reasons recorded on `sessions.revokedReason` (§6.2). */
export const SESSION_REVOKE_REASONS = [
  "logout",
  "admin_revoke",
  "privilege_reduction",
  "password_change",
  "expired_sweep",
] as const;
export const SessionRevokeReasonSchema = z.enum(SESSION_REVOKE_REASONS);
export type SessionRevokeReason = (typeof SESSION_REVOKE_REASONS)[number];

export type LoginRequest = z.infer<typeof LoginRequestSchema>;
export type MfaVerifyRequest = z.infer<typeof MfaVerifyRequestSchema>;
export type InvitationCreate = z.infer<typeof InvitationCreateSchema>;
export type UserUpdate = z.infer<typeof UserUpdateSchema>;
