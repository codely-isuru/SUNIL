/**
 * API configuration (§16, FR-004, FR-023).
 *
 * Values come from `parseEnv(CoreEnvSchema)` in `@sunil/core` — the single canonical env
 * schema — and nothing here invents a default that the schema does not already declare.
 *
 * The class exists (rather than a plain object) for one reason: the master key and the two
 * DSNs are credential material, and a plain object would happily serialise them into a log
 * line or an error payload. `toJSON()` returns the non-sensitive subset, so the config
 * cannot leak by accident; key material is reachable only through the explicit accessors
 * the `EnvelopeSecretStore` calls.
 */
import {
  CoreEnvSchema,
  assertProductionCookiePolicy,
  parseEnv,
  ConfigurationError,
} from "@sunil/core";
import { sessionCookieName } from "../common/cookies.js";

export interface ApiConfigSafeView {
  readonly nodeEnv: string;
  readonly port: number;
  readonly cookieSecure: boolean;
  readonly cookieName: string;
  readonly sessionIdleHours: number;
  readonly sessionAbsoluteHours: number;
  readonly authMaxFailures: number;
  readonly authFailureWindowMinutes: number;
  readonly authLockoutMinutes: number;
  readonly rateSessionPerMinute: number;
  readonly rateAuthIpPerMinute: number;
  readonly inviteTtlHours: number;
  readonly timezone: string;
  readonly masterKeyVersion: number;
  readonly hasPreviousMasterKey: boolean;
}

export class ApiConfig {
  readonly nodeEnv: string;
  readonly port: number;
  readonly cookieSecure: boolean;
  readonly cookieName: string;
  readonly sessionIdleHours: number;
  readonly sessionAbsoluteHours: number;
  readonly authMaxFailures: number;
  readonly authFailureWindowMinutes: number;
  readonly authLockoutMinutes: number;
  readonly rateSessionPerMinute: number;
  readonly rateAuthIpPerMinute: number;
  readonly inviteTtlHours: number;
  readonly timezone: string;
  readonly masterKeyVersion: number;

  readonly #databaseUrl: string;
  readonly #redisUrl: string;
  readonly #masterKey: Buffer;
  readonly #previousMasterKey: Buffer | null;

  private constructor(args: {
    nodeEnv: string;
    port: number;
    cookieSecure: boolean;
    sessionIdleHours: number;
    sessionAbsoluteHours: number;
    authMaxFailures: number;
    authFailureWindowMinutes: number;
    authLockoutMinutes: number;
    rateSessionPerMinute: number;
    rateAuthIpPerMinute: number;
    inviteTtlHours: number;
    timezone: string;
    masterKeyVersion: number;
    databaseUrl: string;
    redisUrl: string;
    masterKey: Buffer;
    previousMasterKey: Buffer | null;
  }) {
    this.nodeEnv = args.nodeEnv;
    this.port = args.port;
    this.cookieSecure = args.cookieSecure;
    this.cookieName = sessionCookieName(args.cookieSecure);
    this.sessionIdleHours = args.sessionIdleHours;
    this.sessionAbsoluteHours = args.sessionAbsoluteHours;
    this.authMaxFailures = args.authMaxFailures;
    this.authFailureWindowMinutes = args.authFailureWindowMinutes;
    this.authLockoutMinutes = args.authLockoutMinutes;
    this.rateSessionPerMinute = args.rateSessionPerMinute;
    this.rateAuthIpPerMinute = args.rateAuthIpPerMinute;
    this.inviteTtlHours = args.inviteTtlHours;
    this.timezone = args.timezone;
    this.masterKeyVersion = args.masterKeyVersion;
    this.#databaseUrl = args.databaseUrl;
    this.#redisUrl = args.redisUrl;
    this.#masterKey = args.masterKey;
    this.#previousMasterKey = args.previousMasterKey;
  }

  /**
   * Fail fast, naming the offending variable and never printing a value (FR-004), and
   * hard-fail a production profile whose cookie policy is explicitly permissive (FR-023).
   */
  static load(env: NodeJS.ProcessEnv = process.env): ApiConfig {
    const parsed = parseEnv(CoreEnvSchema, env);
    const nodeEnv = env["NODE_ENV"] ?? "development";
    assertProductionCookiePolicy(nodeEnv, parsed.SUNIL_COOKIE_SECURE);

    const masterKey = Buffer.from(parsed.SUNIL_MASTER_KEY, "base64");
    if (masterKey.length !== 32) {
      // Defence in depth: `CoreEnvSchema` already checks this, but the store must never be
      // constructed with a short key even if the schema is ever relaxed.
      throw new ConfigurationError("SUNIL_MASTER_KEY must be base64 of exactly 32 bytes", [
        "SUNIL_MASTER_KEY",
      ]);
    }

    const previous = parsed.SUNIL_MASTER_KEY_PREVIOUS
      ? Buffer.from(parsed.SUNIL_MASTER_KEY_PREVIOUS, "base64")
      : null;

    return new ApiConfig({
      nodeEnv,
      port: parsed.SUNIL_PORT_API,
      cookieSecure: parsed.SUNIL_COOKIE_SECURE,
      sessionIdleHours: parsed.SUNIL_SESSION_IDLE_HOURS,
      sessionAbsoluteHours: parsed.SUNIL_SESSION_ABSOLUTE_HOURS,
      authMaxFailures: parsed.SUNIL_AUTH_MAX_FAILURES,
      authFailureWindowMinutes: parsed.SUNIL_AUTH_FAILURE_WINDOW_MIN,
      authLockoutMinutes: parsed.SUNIL_AUTH_LOCKOUT_MIN,
      rateSessionPerMinute: parsed.SUNIL_RATE_SESSION_PER_MIN,
      rateAuthIpPerMinute: parsed.SUNIL_RATE_AUTH_IP_PER_MIN,
      inviteTtlHours: parsed.SUNIL_INVITE_TTL_HOURS,
      timezone: parsed.SUNIL_TIMEZONE,
      masterKeyVersion: parsed.SUNIL_MASTER_KEY_VERSION,
      databaseUrl: parsed.DATABASE_URL,
      redisUrl: parsed.REDIS_URL,
      masterKey,
      previousMasterKey: previous,
    });
  }

  /** Credential-shaped accessors. Deliberately methods, so they never appear in a spread. */
  databaseUrl(): string {
    return this.#databaseUrl;
  }

  redisUrl(): string {
    return this.#redisUrl;
  }

  masterKey(): Buffer {
    return this.#masterKey;
  }

  previousMasterKey(): Buffer | null {
    return this.#previousMasterKey;
  }

  get isProduction(): boolean {
    return this.nodeEnv === "production";
  }

  /** What a log line or an error payload may see. No DSN, no key material. */
  toJSON(): ApiConfigSafeView {
    return {
      nodeEnv: this.nodeEnv,
      port: this.port,
      cookieSecure: this.cookieSecure,
      cookieName: this.cookieName,
      sessionIdleHours: this.sessionIdleHours,
      sessionAbsoluteHours: this.sessionAbsoluteHours,
      authMaxFailures: this.authMaxFailures,
      authFailureWindowMinutes: this.authFailureWindowMinutes,
      authLockoutMinutes: this.authLockoutMinutes,
      rateSessionPerMinute: this.rateSessionPerMinute,
      rateAuthIpPerMinute: this.rateAuthIpPerMinute,
      inviteTtlHours: this.inviteTtlHours,
      timezone: this.timezone,
      masterKeyVersion: this.masterKeyVersion,
      hasPreviousMasterKey: this.#previousMasterKey !== null,
    };
  }

  toString(): string {
    return `ApiConfig(${this.nodeEnv})`;
  }

  [Symbol.for("nodejs.util.inspect.custom")](): ApiConfigSafeView {
    return this.toJSON();
  }
}
