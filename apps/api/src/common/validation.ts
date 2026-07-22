/**
 * The Zod boundary (§13: "all routes: Zod-validated input").
 *
 * Every handler parses its input through one of these helpers, so a validation failure is
 * always a `ValidationError` carrying FIELD PATHS ONLY — never the offending value, which
 * may be a password or a secret (FR-030/FR-042).
 */
import { ValidationError, ZodError, type z } from "@sunil/core";

export function parseInput<T extends z.ZodType>(schema: T, input: unknown): z.output<T> {
  const result = schema.safeParse(input);
  if (result.success) return result.data as z.output<T>;
  throw toValidationError(result.error);
}

export function toValidationError(error: ZodError): ValidationError {
  const fields = [...new Set(error.issues.map((issue) => issue.path.join(".") || "<root>"))];
  const message = error.issues
    .map((issue) => `${issue.path.join(".") || "<root>"}: ${issue.message}`)
    .join("; ");
  return new ValidationError(message, fields);
}

export function isZodError(error: unknown): error is ZodError {
  return error instanceof ZodError;
}
