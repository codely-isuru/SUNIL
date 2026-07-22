/**
 * Session lifecycle (§6.1/§6.2, ADR-003).
 *
 * The state machine, hand-rolled per ADR-003; the primitives, never. What the server holds
 * is `sha256(token)` — theft of the database yields no usable cookie. Elevation out of
 * `PENDING_MFA` ROTATES the token (anti-fixation, THREAT_MODEL T-02), and expiry is
 * enforced at validation time on every single request, so a revocation takes effect on the
 * next request with no cache to invalidate (Gate 1).
 */
import type { SessionRepository, SunilPrismaClient, TransactionClient } from "@sunil/db";
import type { SessionRevokeReason } from "@sunil/core";
import { randomToken, sha256Hex } from "../common/crypto.js";
import type { ApiConfig } from "../config/api-config.js";
import type { IssuedSession, ValidatedSession } from "./session.types.js";

/** Write-amplification guard: at most one sliding-refresh write per session per minute. */
const SLIDING_REFRESH_THROTTLE_MS = 60_000;

export interface CreateSessionArgs {
  readonly userId: string;
  readonly state: "ACTIVE" | "PENDING_MFA";
  readonly ip: string | null;
  readonly userAgent: string | null;
}

export class SessionService {
  readonly #prisma: SunilPrismaClient;
  readonly #sessions: SessionRepository;
  readonly #config: ApiConfig;

  constructor(prisma: SunilPrismaClient, sessions: SessionRepository, config: ApiConfig) {
    this.#prisma = prisma;
    this.#sessions = sessions;
    this.#config = config;
  }

  get cookieName(): string {
    return this.#config.cookieName;
  }

  /**
   * Create a session row inside the caller's audited transaction and return the raw token
   * ONCE. The raw token is never persisted and never logged.
   */
  async create(tx: TransactionClient, args: CreateSessionArgs): Promise<IssuedSession> {
    const token = randomToken(32);
    const csrfSecret = randomToken(32);
    const now = new Date();
    const idleExpiresAt = new Date(now.getTime() + this.#config.sessionIdleHours * 3_600_000);
    const absoluteExpiresAt = new Date(
      now.getTime() + this.#config.sessionAbsoluteHours * 3_600_000,
    );

    const session = await this.#sessions.create(tx, {
      tokenHash: sha256Hex(token),
      user: { connect: { id: args.userId } },
      state: args.state,
      csrfSecret,
      idleExpiresAt,
      absoluteExpiresAt,
      ip: args.ip,
      userAgent: args.userAgent,
    });

    return { token, sessionId: session.id, csrfSecret, absoluteExpiresAt };
  }

  /**
   * Token rotation on MFA elevation (§6.2). The row is kept — its id, creation time and
   * absolute expiry are the audit trail — but the token hash and the CSRF secret are both
   * replaced, so a token captured before elevation is worthless afterwards.
   */
  async elevate(tx: TransactionClient, sessionId: string): Promise<IssuedSession> {
    const token = randomToken(32);
    const csrfSecret = randomToken(32);
    const updated = await tx.session.update({
      where: { id: sessionId },
      data: { tokenHash: sha256Hex(token), csrfSecret, state: "ACTIVE", lastSeenAt: new Date() },
    });
    return {
      token,
      sessionId: updated.id,
      csrfSecret,
      absoluteExpiresAt: updated.absoluteExpiresAt,
    };
  }

  /**
   * The per-request validation (§6.2). Every condition is checked against the row, on every
   * request: there is no in-memory session cache in Phase 1, deliberately.
   */
  async validate(token: string): Promise<ValidatedSession | null> {
    const row = await this.#prisma.session.findUnique({
      where: { tokenHash: sha256Hex(token) },
      include: { user: true },
    });
    if (!row) return null;
    if (row.state === "REVOKED" || row.revokedAt !== null) return null;

    const now = new Date();
    if (row.idleExpiresAt <= now || row.absoluteExpiresAt <= now) return null;
    if (row.user.status !== "ACTIVE") return null;

    // Sliding refresh — bookkeeping, not a security decision, so it is not audited and is
    // throttled to one write per minute per session (§6.2).
    if (now.getTime() - row.lastSeenAt.getTime() > SLIDING_REFRESH_THROTTLE_MS) {
      const idleExpiresAt = new Date(now.getTime() + this.#config.sessionIdleHours * 3_600_000);
      await this.#sessions.touch(row.id, idleExpiresAt);
    }

    return {
      id: row.id,
      userId: row.userId,
      state: row.state,
      csrfSecret: row.csrfSecret,
      createdAt: row.createdAt,
      idleExpiresAt: row.idleExpiresAt,
      absoluteExpiresAt: row.absoluteExpiresAt,
      user: {
        id: row.user.id,
        email: row.user.email,
        displayName: row.user.displayName,
        status: row.user.status,
        timezone: row.user.timezone,
        mfaEnabled: row.user.mfaEnabled,
        createdAt: row.user.createdAt,
      },
    };
  }

  revoke(
    tx: TransactionClient,
    sessionId: string,
    reason: SessionRevokeReason,
  ): Promise<{ id: string }> {
    return this.#sessions.revoke(tx, sessionId, reason);
  }

  /** Used by logout-everywhere, admin bulk revoke and the §6.6 privilege-reduction hook. */
  revokeAllForUser(
    tx: TransactionClient,
    userId: string,
    reason: SessionRevokeReason,
    exceptSessionId?: string,
  ): Promise<{ count: number }> {
    return this.#sessions.revokeAllForUser(tx, userId, reason, exceptSessionId);
  }

  listForUser(userId: string) {
    return this.#sessions.listForUser(userId);
  }

  findById(id: string) {
    return this.#prisma.session.findUnique({ where: { id } });
  }
}
