/**
 * SecretStore contracts (§8.1) — interface and metadata shapes only.
 *
 * `SecretValue` lives here (not in `packages/db`) because it is the type every consumer
 * handles, and the whole point of §8.4 is that the plaintext is unreachable except through
 * `use(fn)` on the server.
 */
import { z } from "../zod.js";
import { UuidSchema } from "./common.js";

/** Everything an API is EVER allowed to return about a secret (§8.4 DTO allowlist). */
export const SecretMetadataSchema = z.object({
  id: UuidSchema,
  name: z.string(),
  description: z.string(),
  /** The only value-derived datum any API returns (FR-042, §8.3). */
  fingerprint: z.string(),
  version: z.number().int().positive(),
  masterKeyVersion: z.number().int().positive(),
  rotatedAt: z.coerce.date().nullish(),
  createdAt: z.coerce.date(),
  updatedAt: z.coerce.date(),
});

export type SecretMetadata = z.infer<typeof SecretMetadataSchema>;

export const SecretNameSchema = z
  .string()
  .trim()
  .min(1)
  .max(200)
  .regex(/^[a-z0-9][a-z0-9._:-]*$/, {
    message: "must be lowercase alphanumeric with . _ : - separators",
  });

export const SecretCreateSchema = z.object({
  name: SecretNameSchema,
  value: z.string().min(1).max(65536),
  description: z.string().trim().max(1000).default(""),
});

export const SecretRotateSchema = z.object({
  value: z.string().min(1).max(65536),
});

/**
 * A wrapper whose plaintext cannot be serialised by accident.
 *
 * `toJSON()`, `toString()` and `util.inspect.custom` all yield `[REDACTED]`, so if this ever
 * lands in a response body, a log line or a template string, the marker appears — not the
 * value. The plaintext is reachable only inside `use(fn)`.
 *
 * Warning §18.5: if you need the plaintext, you are inside `use(fn)` on the server, or you
 * are doing it wrong.
 */
export class SecretValue {
  static readonly REDACTED = "[REDACTED]";

  readonly #plaintext: string;
  readonly name: string;

  constructor(name: string, plaintext: string) {
    this.name = name;
    this.#plaintext = plaintext;
  }

  /** The ONLY way to read the plaintext. Keep the callback tight and synchronous-ish. */
  use<T>(fn: (plaintext: string) => T): T {
    return fn(this.#plaintext);
  }

  toJSON(): string {
    return SecretValue.REDACTED;
  }

  toString(): string {
    return SecretValue.REDACTED;
  }

  /** Node's `util.inspect` / console.log path. */
  [Symbol.for("nodejs.util.inspect.custom")](): string {
    return SecretValue.REDACTED;
  }

  get [Symbol.toStringTag](): string {
    return "SecretValue";
  }
}

export function isSecretValue(value: unknown): value is SecretValue {
  return value instanceof SecretValue;
}

/**
 * Two implementations exist: `EnvelopeSecretStore` (Phase 1) and `InMemorySecretStore`
 * (test double). Consumers depend only on this interface — that is FR-040's swappability.
 */
export interface SecretStore {
  put(name: string, plaintext: string, meta?: { description?: string }): Promise<SecretMetadata>;
  get(name: string): Promise<SecretValue>;
  rotate(name: string, newPlaintext: string): Promise<SecretMetadata>;
  delete(name: string): Promise<void>;
  describe(name: string): Promise<SecretMetadata>;
}

/** Reference-name conventions so two subsystems cannot invent two schemes. */
export const secretNameFor = {
  totp: (userId: string): string => `mfa:totp:${userId}`,
  providerCredential: (providerSlug: string): string => `llm:${providerSlug}:api-key`,
} as const;
