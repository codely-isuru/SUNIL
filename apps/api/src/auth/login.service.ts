/**
 * Login and brute-force mechanics (§6.3, FR-022/FR-029, ET-1 1.2–1.4).
 *
 * The order of operations is the specification's, and it matters:
 *   lockout check → credential check (ALWAYS against a hash) → success or failure counting.
 *
 * Step 3 is the interesting one. When no user row matches the submitted email we still
 * verify the submitted password against a dummy argon2 hash (`getDummyPasswordHash` from
 * `@sunil/db`). Without it, "unknown email" returns in microseconds and "known email, wrong
 * password" returns in ~50 ms — an account-existence oracle that no amount of identical
 * error text would hide (FR-022, ET-1 1.3).
 */
import {
  LockedOutError,
  UnauthenticatedError,
  type SessionRevokeReason,
} from "@sunil/core";
import { getDummyPasswordHash, verifyPassword, type UserRepository } from "@sunil/db";
import { sha256Hex } from "../common/crypto.js";
import type { ApiConfig } from "../config/api-config.js";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import type { DenialRecorder } from "../audit/denial-recorder.js";
import type { CounterStore } from "../ratelimit/counter-store.js";
import type { SessionService } from "./session.service.js";
import type { IssuedSession, SessionUser } from "./session.types.js";

export interface LoginArgs {
  readonly email: string;
  readonly password: string;
  readonly ip: string | null;
  readonly userAgent: string | null;
}

export interface LoginResult {
  readonly user: SessionUser;
  readonly session: IssuedSession;
  readonly mfaRequired: boolean;
}

/** Emails are hashed into Redis keys — the counter substrate never holds an address. */
function failureKey(email: string): string {
  return `authfail:${sha256Hex(email)}`;
}

function lockoutKey(email: string): string {
  return `lockout:${sha256Hex(email)}`;
}

export class LoginService {
  readonly #users: UserRepository;
  readonly #sessions: SessionService;
  readonly #counters: CounterStore;
  readonly #uow: AuditedUnitOfWork;
  readonly #denials: DenialRecorder;
  readonly #config: ApiConfig;

  constructor(
    users: UserRepository,
    sessions: SessionService,
    counters: CounterStore,
    uow: AuditedUnitOfWork,
    denials: DenialRecorder,
    config: ApiConfig,
  ) {
    this.#users = users;
    this.#sessions = sessions;
    this.#counters = counters;
    this.#uow = uow;
    this.#denials = denials;
    this.#config = config;
  }

  async login(args: LoginArgs): Promise<LoginResult> {
    // §6.3 step 2 — lockout is checked BEFORE credentials, so a locked account cannot be
    // probed and a correct password during lockout still fails (ET-1 1.4).
    const lockoutTtl = await this.#counters.ttl(lockoutKey(args.email));
    if (lockoutTtl !== null) {
      await this.#denials.record({
        action: "auth.login.lockout",
        denialReason: "locked_out",
        targetType: "user",
        after: { emailFingerprint: sha256Hex(args.email).slice(0, 12) },
      });
      throw new LockedOutError(lockoutTtl);
    }

    const user = await this.#users.findByEmail(args.email);

    // §6.3 step 3 — timing equalisation. The dummy verify is not an optimisation target;
    // deleting it re-introduces the oracle.
    const storedHash = user?.passwordHash ?? (await getDummyPasswordHash());
    const passwordOk = await verifyPassword(storedHash, args.password);

    if (!user || !passwordOk || user.status !== "ACTIVE") {
      await this.#registerFailure(args.email);
      await this.#denials.record({
        action: "auth.login.failure",
        denialReason: "unauthenticated",
        targetType: "user",
        targetId: user?.id ?? null,
      });
      // One generic error for every failure mode: unknown email, wrong password, disabled
      // account. The caller cannot tell them apart (FR-022, ET-1 1.3).
      throw new UnauthenticatedError("Invalid credentials");
    }

    await this.#counters.delete(failureKey(args.email));

    const mfaRequired = user.mfaEnabled;
    const session = await this.#uow.runAudited(
      {
        action: "auth.login.success",
        targetType: "user",
        targetId: user.id,
        outcome: "SUCCESS",
        after: { mfaRequired },
        actorOverride: { actorType: "HUMAN", actorId: user.id, actorLabel: user.email },
      },
      (tx) =>
        this.#sessions.create(tx, {
          userId: user.id,
          state: mfaRequired ? "PENDING_MFA" : "ACTIVE",
          ip: args.ip,
          userAgent: args.userAgent,
        }),
    );

    return {
      user: {
        id: user.id,
        email: user.email,
        displayName: user.displayName,
        status: user.status,
        timezone: user.timezone,
        mfaEnabled: user.mfaEnabled,
        createdAt: user.createdAt,
      },
      session,
      mfaRequired,
    };
  }

  /** 5 failures inside a 15-minute window arms a 15-minute lockout (Gate 1 defaults, §16). */
  async #registerFailure(email: string): Promise<void> {
    const { count } = await this.#counters.increment(
      failureKey(email),
      this.#config.authFailureWindowMinutes * 60,
    );
    if (count >= this.#config.authMaxFailures) {
      await this.#counters.setMarker(lockoutKey(email), this.#config.authLockoutMinutes * 60);
    }
  }

  /** Owner intervention: `POST /api/users/:id/lockout/clear` (FR-029). */
  async clearLockout(email: string): Promise<void> {
    await this.#counters.delete(lockoutKey(email));
    await this.#counters.delete(failureKey(email));
  }

  /** Password changes revoke the user's other sessions (§6.2). */
  static readonly PASSWORD_CHANGE_REASON: SessionRevokeReason = "password_change";
}
