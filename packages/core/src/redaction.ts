/**
 * The single redaction module (PHASE1_ARCHITECTURE §9.5, NFR-011).
 *
 * ONE implementation feeds two consumers:
 *  - audit `before`/`after` payloads, redacted before persist;
 *  - Pino's `redact.paths`, so logs and audit records cannot diverge.
 *
 * There is no second redaction list anywhere in this repository. If you need to redact a
 * new field, add it here.
 */

export const REDACTED = "[REDACTED]" as const;

/** Named-field deny-list, matched case-insensitively against the key name. */
export const REDACTED_FIELD_NAMES: readonly string[] = [
  "password",
  "newPassword",
  "currentPassword",
  "passwordHash",
  "apiKey",
  "api_key",
  "token",
  "tokenHash",
  "accessToken",
  "refreshToken",
  "secret",
  "secretValue",
  "clientSecret",
  "authorization",
  "cookie",
  "setCookie",
  "set-cookie",
  "recoveryCode",
  "recoveryCodes",
  "totp",
  "totpSecret",
  "csrfSecret",
  "masterKey",
  "plaintext",
  "ciphertext",
  "wrappedDek",
  "dek",
];

const FIELD_DENY_SET = new Set(REDACTED_FIELD_NAMES.map((f) => f.toLowerCase()));

/**
 * Pattern scrubbing for values that look like credential material wherever they appear.
 * Deliberately conservative: a false positive costs a redacted log line, a false negative
 * costs a leaked key.
 */
const VALUE_PATTERNS: readonly RegExp[] = [
  // PEM blocks
  /-----BEGIN[\s\S]*?-----END[^-]*-----/g,
  // Provider-style API keys (sk-…, sk-ant-…, xoxb-…, ghp_…)
  /\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b/g,
  /\bsk-ant-[A-Za-z0-9_-]{16,}\b/g,
  /\bghp_[A-Za-z0-9]{20,}\b/g,
  /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/g,
  // JWTs
  /\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b/g,
  // postgres/redis connection strings carrying credentials
  /\b(?:postgres(?:ql)?|redis|rediss|mysql|amqp):\/\/[^\s"']*:[^\s"'@]*@[^\s"']+/g,
];

/** Long base64/hex runs are only scrubbed inside known-sensitive field names (§9.5). */
const LONG_BASE64 = /\b[A-Za-z0-9+/=_-]{32,}\b/g;

export function isRedactedFieldName(name: string): boolean {
  return FIELD_DENY_SET.has(name.toLowerCase());
}

/** Scrub credential-shaped substrings out of a free-text value. */
export function scrubString(value: string): string {
  let out = value;
  for (const pattern of VALUE_PATTERNS) {
    out = out.replace(pattern, REDACTED);
  }
  return out;
}

interface RedactOptions {
  /** Guard against pathological/cyclic structures. */
  readonly maxDepth?: number;
}

/**
 * Deep-redact an arbitrary payload. Field-name matches are replaced wholesale; every
 * remaining string is pattern-scrubbed. Cycles are broken with `[CIRCULAR]`.
 */
export function redact(value: unknown, options: RedactOptions = {}): unknown {
  const maxDepth = options.maxDepth ?? 12;
  return redactInner(value, maxDepth, new WeakSet<object>(), false);
}

function redactInner(
  value: unknown,
  depthRemaining: number,
  seen: WeakSet<object>,
  insideSensitiveField: boolean,
): unknown {
  if (value === null || value === undefined) return value;

  if (typeof value === "string") {
    const scrubbed = scrubString(value);
    return insideSensitiveField ? scrubbed.replace(LONG_BASE64, REDACTED) : scrubbed;
  }

  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return typeof value === "bigint" ? value.toString() : value;
  }

  if (value instanceof Date) return value.toISOString();
  if (value instanceof Error) return { name: value.name, message: scrubString(value.message) };

  if (typeof value !== "object") return REDACTED;

  if (depthRemaining <= 0) return "[TRUNCATED]";
  if (seen.has(value as object)) return "[CIRCULAR]";
  seen.add(value as object);

  if (Array.isArray(value)) {
    return value.map((item) =>
      redactInner(item, depthRemaining - 1, seen, insideSensitiveField),
    );
  }

  const out: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    if (isRedactedFieldName(key)) {
      out[key] = REDACTED;
      continue;
    }
    out[key] = redactInner(item, depthRemaining - 1, seen, insideSensitiveField);
  }
  return out;
}

/**
 * Paths handed to Pino's `redact` option. Pino matches literal paths and wildcards, so the
 * common request/response shapes are enumerated explicitly in addition to the deep
 * `redact()` used for audit payloads.
 */
export const PINO_REDACT_PATHS: readonly string[] = [
  "req.headers.authorization",
  "req.headers.cookie",
  'req.headers["x-csrf-token"]',
  "res.headers['set-cookie']",
  ...REDACTED_FIELD_NAMES.flatMap((f) => [f, `*.${f}`, `req.body.${f}`, `body.${f}`]),
];
