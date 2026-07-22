/** Primitive boundary schemas shared by every other schema module. */
import { z } from "../zod.js";

/**
 * Email normalisation happens HERE, at the Zod boundary (§5.1), so the plain unique index
 * on `users.email` is effectively case-insensitive without the `citext` extension.
 */
export const EmailSchema = z
  .string()
  .trim()
  .toLowerCase()
  .max(320)
  .pipe(z.email({ message: "must be a valid email address" }));

export const UuidSchema = z.uuid();

export const CorrelationIdSchema = z.string().min(1).max(128);

export const NonEmptyStringSchema = z.string().trim().min(1);

/** FR-030: documented minimum policy, enforced at set-password time. */
export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_LENGTH = 200;

/**
 * A deliberately short, obvious weak-password list. It is a policy floor, not a breach
 * corpus; the requirement is a documented rejection list, and expanding it is a data change
 * rather than a code change.
 */
export const WEAK_PASSWORDS: readonly string[] = [
  "password",
  "password1",
  "password123",
  "passw0rd",
  "letmein",
  "qwertyuiop",
  "administrator",
  "changeme",
  "welcome1",
  "iloveyou",
  "sunil",
  "sunilsunil",
  "123456789012",
  "1234567890123",
  "abcdefghijkl",
];

const WEAK_SET = new Set(WEAK_PASSWORDS);

/**
 * Never echo the submitted value in an error message (FR-030). All messages here are
 * value-free by construction.
 */
export const PasswordSchema = z
  .string()
  .min(PASSWORD_MIN_LENGTH, {
    message: `must be at least ${PASSWORD_MIN_LENGTH} characters`,
  })
  .max(PASSWORD_MAX_LENGTH, {
    message: `must be at most ${PASSWORD_MAX_LENGTH} characters`,
  })
  .refine((value) => !WEAK_SET.has(value.toLowerCase()), {
    message: "is on the rejected-password list",
  })
  .refine((value) => !/^(.)\1+$/.test(value), {
    message: "must not be a single repeated character",
  });

export const PageRequestSchema = z.object({
  page: z.coerce.number().int().min(1).default(1),
  pageSize: z.coerce.number().int().min(1).max(200).default(50),
});

export type PageRequestInput = z.input<typeof PageRequestSchema>;

/** Build the standard paged response shape for any item schema. */
export function pagedSchema<T extends z.ZodType>(item: T) {
  return z.object({
    items: z.array(item),
    page: z.number().int(),
    pageSize: z.number().int(),
    total: z.number().int(),
    hasMore: z.boolean(),
  });
}
