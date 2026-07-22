/** Shapes the session layer hands to guards, services and controllers. */
import type { SessionState, UserStatus } from "@sunil/core";

export interface SessionUser {
  readonly id: string;
  readonly email: string;
  readonly displayName: string;
  readonly status: UserStatus;
  readonly timezone: string;
  readonly mfaEnabled: boolean;
  readonly createdAt: Date;
}

export interface ValidatedSession {
  readonly id: string;
  readonly userId: string;
  readonly state: SessionState;
  readonly csrfSecret: string;
  readonly createdAt: Date;
  readonly idleExpiresAt: Date;
  readonly absoluteExpiresAt: Date;
  readonly user: SessionUser;
}

export interface IssuedSession {
  /** The raw cookie token. Returned exactly once, at creation; never stored (§6.1). */
  readonly token: string;
  readonly sessionId: string;
  readonly csrfSecret: string;
  readonly absoluteExpiresAt: Date;
}
