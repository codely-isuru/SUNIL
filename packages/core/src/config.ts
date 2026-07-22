/**
 * Configuration inventory — NAMES ONLY (PHASE1_ARCHITECTURE §16, NFR-005).
 *
 * No value of any variable appears in this repository. This module is the single canonical
 * list of variable names, so the FR-092 test can diff code against `.env.example` and keep
 * them in lockstep. Defaults that are NOT secret (timeouts, thresholds, ports) are declared
 * in the schema below; anything credential-shaped has no default and no fallback.
 */
import { z } from "./zod.js";
import { ConfigurationError } from "./errors.js";

/** Every environment variable read anywhere in the codebase. */
export const ENV_VAR_NAMES = [
  "DATABASE_URL",
  "REDIS_URL",
  "SUNIL_MASTER_KEY",
  "SUNIL_MASTER_KEY_VERSION",
  "SUNIL_MASTER_KEY_PREVIOUS",
  "SUNIL_OWNER_EMAIL",
  "SUNIL_OWNER_INITIAL_PASSWORD",
  "SUNIL_COOKIE_SECURE",
  "SUNIL_SESSION_IDLE_HOURS",
  "SUNIL_SESSION_ABSOLUTE_HOURS",
  "SUNIL_AUTH_MAX_FAILURES",
  "SUNIL_AUTH_FAILURE_WINDOW_MIN",
  "SUNIL_AUTH_LOCKOUT_MIN",
  "SUNIL_RATE_SESSION_PER_MIN",
  "SUNIL_RATE_AUTH_IP_PER_MIN",
  "SUNIL_INVITE_TTL_HOURS",
  "SUNIL_AGENT_HEARTBEAT_SEC",
  "SUNIL_AGENT_STALE_SEC",
  "SUNIL_TIMEZONE",
  "ANTHROPIC_API_KEY",
  "OPENAI_API_KEY",
  "OLLAMA_BASE_URL",
  "SUNIL_PORT_WEB",
  "SUNIL_PORT_API",
  // ADR-011 / Amendment A1: the Next `rewrites()` target and the server-component fetch
  // base. SERVER-SIDE ONLY — it must never reach the browser bundle.
  "SUNIL_API_INTERNAL_URL",
] as const;

/**
 * Deliberately absent from the inventory (Amendment A1) — recorded here so nobody
 * "helpfully" re-adds one:
 *
 *  - `NEXT_PUBLIC_API_URL`. Browser↔API is strictly same-origin via the Next rewrite proxy,
 *    so client code fetches relative `/api/...` paths. Nothing API-shaped belongs in the
 *    client bundle, and a `NEXT_PUBLIC_` name is by definition in the bundle.
 *  - Any CORS / allowed-origins variable. The API is same-origin only by design; a future
 *    cross-origin client requires a new ADR, not a config addition.
 */
export const DELIBERATELY_ABSENT_ENV_VAR_NAMES: readonly string[] = [
  "NEXT_PUBLIC_API_URL",
  "SUNIL_CORS_ORIGINS",
  "SUNIL_ALLOWED_ORIGINS",
  "CORS_ORIGIN",
];

export type EnvVarName = (typeof ENV_VAR_NAMES)[number];

/** Variables whose VALUES must never be printed, logged or echoed in an error (FR-004). */
export const SECRET_ENV_VAR_NAMES: readonly EnvVarName[] = [
  "DATABASE_URL",
  "REDIS_URL",
  "SUNIL_MASTER_KEY",
  "SUNIL_MASTER_KEY_PREVIOUS",
  "SUNIL_OWNER_INITIAL_PASSWORD",
  "ANTHROPIC_API_KEY",
  "OPENAI_API_KEY",
];

const booleanish = z
  .string()
  .trim()
  .toLowerCase()
  .pipe(z.enum(["true", "false", "1", "0"]))
  .transform((v) => v === "true" || v === "1");

const positiveInt = z.coerce.number().int().positive();

/** A base64-encoded 32-byte key. Length is validated, the value is never surfaced. */
const masterKeySchema = z
  .string()
  .min(1)
  .refine(
    (value) => {
      try {
        return Buffer.from(value, "base64").length === 32;
      } catch {
        return false;
      }
    },
    { message: "must be base64 of exactly 32 bytes" },
  );

/**
 * Shared shape. Each app composes the subset it actually needs — `apps/web` for example
 * reads only `SUNIL_API_INTERNAL_URL` (server-side; ADR-011) and must never see
 * `SUNIL_MASTER_KEY` or any datastore URL (§14).
 */
export const CoreEnvSchema = z.object({
  DATABASE_URL: z.string().min(1),
  REDIS_URL: z.string().min(1),
  SUNIL_MASTER_KEY: masterKeySchema,
  SUNIL_MASTER_KEY_VERSION: positiveInt.default(1),
  SUNIL_MASTER_KEY_PREVIOUS: masterKeySchema.optional(),
  SUNIL_COOKIE_SECURE: booleanish.default(true),
  SUNIL_SESSION_IDLE_HOURS: positiveInt.default(8),
  SUNIL_SESSION_ABSOLUTE_HOURS: positiveInt.default(24),
  SUNIL_AUTH_MAX_FAILURES: positiveInt.default(5),
  SUNIL_AUTH_FAILURE_WINDOW_MIN: positiveInt.default(15),
  SUNIL_AUTH_LOCKOUT_MIN: positiveInt.default(15),
  SUNIL_RATE_SESSION_PER_MIN: positiveInt.default(100),
  SUNIL_RATE_AUTH_IP_PER_MIN: positiveInt.default(20),
  SUNIL_INVITE_TTL_HOURS: positiveInt.default(72),
  SUNIL_AGENT_HEARTBEAT_SEC: positiveInt.default(30),
  SUNIL_AGENT_STALE_SEC: positiveInt.default(90),
  SUNIL_TIMEZONE: z.string().min(1).default("Australia/Hobart"),
  OLLAMA_BASE_URL: z.url().optional(),
  SUNIL_PORT_API: positiveInt.default(3001),
  SUNIL_PORT_WEB: positiveInt.default(3000),
});

/** Bootstrap-time only. Never read by a running service (§5.8, FR-014). */
export const BootstrapEnvSchema = z.object({
  DATABASE_URL: z.string().min(1),
  SUNIL_MASTER_KEY: masterKeySchema,
  SUNIL_MASTER_KEY_VERSION: positiveInt.default(1),
  SUNIL_OWNER_EMAIL: z.string().min(3),
  SUNIL_OWNER_INITIAL_PASSWORD: z.string().min(1),
  SUNIL_TIMEZONE: z.string().min(1).default("Australia/Hobart"),
});

/**
 * Parse a schema against `process.env`, failing fast and naming the offending variables.
 * The thrown message contains variable NAMES and validation messages only — never a value
 * (FR-004). Callers exit non-zero on this error.
 */
export function parseEnv<T extends z.ZodType<Record<string, unknown>>>(
  schema: T,
  source: NodeJS.ProcessEnv = process.env,
): z.infer<T> {
  const result = schema.safeParse(source);
  if (result.success) return result.data as z.infer<T>;

  const names = [...new Set(result.error.issues.map((i) => String(i.path[0] ?? "<root>")))];
  const details = result.error.issues
    .map((i) => `${String(i.path[0] ?? "<root>")}: ${i.message}`)
    .join("; ");
  throw new ConfigurationError(`Invalid environment configuration — ${details}`, names);
}

/**
 * FR-023: permissive-by-omission is impossible. In a production profile an explicit
 * `SUNIL_COOKIE_SECURE=false` is a hard startup failure, not a warning.
 */
export function assertProductionCookiePolicy(
  nodeEnv: string | undefined,
  cookieSecure: boolean,
): void {
  if (nodeEnv === "production" && !cookieSecure) {
    throw new ConfigurationError(
      "SUNIL_COOKIE_SECURE must not be false in a production profile",
      ["SUNIL_COOKIE_SECURE"],
    );
  }
}
