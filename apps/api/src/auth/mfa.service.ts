/**
 * TOTP MFA (§6.4, FR-027, ET-1 1.5/1.6).
 *
 * `otpauth` is a pure-JS RFC 6238 implementation (ADR-003) — no TOTP arithmetic is written
 * here, only policy:
 *
 *  - The shared secret is stored through `SecretStore` under `mfa:totp:<userId>`, so it is
 *    envelope-encrypted like every other credential and never a column (FR-027).
 *  - Enrolment returns the `otpauth://` URI and the base32 secret EXACTLY once. That is the
 *    single sanctioned "secret leaves the API" moment (§6.4): it is the enrolment payload,
 *    not a stored-secret read, and it is never retrievable again.
 *  - Replay prevention is a stored high-water mark, not a cache: the accepted code's
 *    timestep is written to `MfaCredential.lastUsedStep`, and any code for a step at or
 *    below it is refused (FR-027 "invalid or reused code").
 */
import {
  ConflictError,
  InvariantViolationError,
  NotFoundError,
  UnauthenticatedError,
  secretNameFor,
  type SecretStore,
} from "@sunil/core";
import { hashPassword, verifyPassword, type SunilPrismaClient } from "@sunil/db";
import { randomRecoveryCode, sha256Hex } from "../common/crypto.js";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import type { DenialRecorder } from "../audit/denial-recorder.js";
import type { SessionService } from "./session.service.js";
import type { IssuedSession, SessionUser } from "./session.types.js";

const TOTP_PERIOD_SECONDS = 30;
const TOTP_DIGITS = 6;
const TOTP_WINDOW = 1;
const RECOVERY_CODE_COUNT = 10;

export interface EnrolmentPayload {
  /** Shown once for QR rendering. Never retrievable again (§6.4). */
  readonly otpauthUri: string;
  readonly secret: string;
}

export class MfaService {
  readonly #prisma: SunilPrismaClient;
  readonly #secrets: SecretStore;
  readonly #uow: AuditedUnitOfWork;
  readonly #denials: DenialRecorder;
  readonly #sessions: SessionService;

  constructor(
    prisma: SunilPrismaClient,
    secrets: SecretStore,
    uow: AuditedUnitOfWork,
    denials: DenialRecorder,
    sessions: SessionService,
  ) {
    this.#prisma = prisma;
    this.#secrets = secrets;
    this.#uow = uow;
    this.#denials = denials;
    this.#sessions = sessions;
  }

  /**
   * `otpauth` is loaded lazily through a helper so the import stays in one place and the
   * construction parameters (SHA-1, 6 digits, 30 s) are stated exactly once.
   */
  async #totpFor(email: string, base32Secret: string) {
    const { Secret, TOTP } = await import("otpauth");
    return new TOTP({
      issuer: "SUNIL",
      label: email,
      algorithm: "SHA1",
      digits: TOTP_DIGITS,
      period: TOTP_PERIOD_SECONDS,
      secret: Secret.fromBase32(base32Secret),
    });
  }

  async enrol(user: SessionUser): Promise<EnrolmentPayload> {
    const existing = await this.#prisma.mfaCredential.findUnique({ where: { userId: user.id } });
    if (existing?.status === "ACTIVE") {
      throw new ConflictError("MFA is already active for this account");
    }

    const { Secret, TOTP } = await import("otpauth");
    const secret = new Secret({ size: 20 });
    const secretName = secretNameFor.totp(user.id);

    // Through the SecretStore, which audits the write itself (§8.5).
    await this.#secrets.put(secretName, secret.base32, {
      description: `TOTP shared secret for ${user.email}`,
    });

    await this.#uow.runAudited(
      {
        action: "auth.mfa.enrol",
        targetType: "user",
        targetId: user.id,
        outcome: "SUCCESS",
        after: { secretName, status: "PENDING" },
      },
      async (tx) => {
        await tx.mfaCredential.upsert({
          where: { userId: user.id },
          create: { userId: user.id, secretName, status: "PENDING" },
          update: { secretName, status: "PENDING", lastUsedStep: null, activatedAt: null },
        });
      },
    );

    const totp = new TOTP({
      issuer: "SUNIL",
      label: user.email,
      algorithm: "SHA1",
      digits: TOTP_DIGITS,
      period: TOTP_PERIOD_SECONDS,
      secret,
    });

    return { otpauthUri: totp.toString(), secret: secret.base32 };
  }

  /**
   * Activation: verify a live code, flip the credential and the denormalised user flag, and
   * issue the recovery codes. The codes are returned once and stored only as SHA-256 —
   * their input is high-entropy, so a slow hash buys nothing (§5.2).
   */
  async activate(user: SessionUser, code: string): Promise<string[]> {
    const credential = await this.#prisma.mfaCredential.findUnique({ where: { userId: user.id } });
    if (!credential) throw new NotFoundError("No MFA enrolment in progress");
    if (credential.status === "ACTIVE") throw new ConflictError("MFA is already active");

    const step = await this.#verifyCode(credential.secretName, user.email, code, credential.lastUsedStep);
    if (step === null) {
      await this.#denials.record({
        action: "auth.mfa.verify.failure",
        denialReason: "unauthenticated",
        targetType: "user",
        targetId: user.id,
      });
      throw new UnauthenticatedError("Invalid MFA code");
    }

    const codes = Array.from({ length: RECOVERY_CODE_COUNT }, () => randomRecoveryCode());

    await this.#uow.runAudited(
      {
        action: "auth.mfa.activate",
        targetType: "user",
        targetId: user.id,
        outcome: "SUCCESS",
        after: { recoveryCodesIssued: codes.length },
      },
      async (tx) => {
        await tx.mfaCredential.update({
          where: { userId: user.id },
          data: { status: "ACTIVE", activatedAt: new Date(), lastUsedStep: step },
        });
        await tx.user.update({ where: { id: user.id }, data: { mfaEnabled: true } });
        await tx.mfaRecoveryCode.deleteMany({ where: { userId: user.id } });
        await tx.mfaRecoveryCode.createMany({
          data: codes.map((value) => ({ userId: user.id, codeHash: sha256Hex(value) })),
        });
      },
    );

    return codes;
  }

  /**
   * The login challenge (§6.2). On success the session token AND the CSRF secret are both
   * rotated inside the same audited transaction — elevation must not preserve a token that
   * existed before authentication completed (THREAT_MODEL T-02).
   */
  async verifyChallenge(args: {
    sessionId: string;
    user: SessionUser;
    code?: string;
    recoveryCode?: string;
  }): Promise<IssuedSession> {
    const credential = await this.#prisma.mfaCredential.findUnique({
      where: { userId: args.user.id },
    });
    if (!credential || credential.status !== "ACTIVE") {
      throw new InvariantViolationError("No active MFA credential for this account");
    }

    if (args.recoveryCode) {
      return this.#verifyRecoveryCode(args.sessionId, args.user, args.recoveryCode);
    }

    const step = await this.#verifyCode(
      credential.secretName,
      args.user.email,
      args.code ?? "",
      credential.lastUsedStep,
    );
    if (step === null) {
      await this.#denials.record({
        action: "auth.mfa.verify.failure",
        denialReason: "unauthenticated",
        targetType: "user",
        targetId: args.user.id,
      });
      throw new UnauthenticatedError("Invalid MFA code");
    }

    return this.#uow.runAudited(
      {
        action: "auth.mfa.verify.success",
        targetType: "session",
        targetId: args.sessionId,
        outcome: "SUCCESS",
        after: { method: "totp" },
        actorOverride: { actorType: "HUMAN", actorId: args.user.id, actorLabel: args.user.email },
      },
      async (tx) => {
        await tx.mfaCredential.update({
          where: { userId: args.user.id },
          data: { lastUsedStep: step },
        });
        return this.#sessions.elevate(tx, args.sessionId);
      },
    );
  }

  /** Single use, enforced by `usedAt IS NULL` inside the transaction (§6.4, ET-1 1.6). */
  async #verifyRecoveryCode(
    sessionId: string,
    user: SessionUser,
    recoveryCode: string,
  ): Promise<IssuedSession> {
    const codeHash = sha256Hex(recoveryCode);
    const row = await this.#prisma.mfaRecoveryCode.findUnique({ where: { codeHash } });
    if (!row || row.userId !== user.id || row.usedAt !== null) {
      await this.#denials.record({
        action: "auth.mfa.verify.failure",
        denialReason: "unauthenticated",
        targetType: "user",
        targetId: user.id,
        after: { method: "recovery-code" },
      });
      throw new UnauthenticatedError("Invalid MFA code");
    }

    return this.#uow.runAudited(
      {
        action: "auth.mfa.verify.success",
        targetType: "session",
        targetId: sessionId,
        outcome: "SUCCESS",
        after: { method: "recovery-code" },
        actorOverride: { actorType: "HUMAN", actorId: user.id, actorLabel: user.email },
      },
      async (tx) => {
        const consumed = await tx.mfaRecoveryCode.updateMany({
          where: { id: row.id, usedAt: null },
          data: { usedAt: new Date() },
        });
        if (consumed.count !== 1) {
          // Lost a race with a concurrent use of the same code — refuse rather than elevate.
          throw new UnauthenticatedError("Invalid MFA code");
        }
        return this.#sessions.elevate(tx, sessionId);
      },
    );
  }

  /** Disabling requires password re-authentication (FR-027) and removes the stored secret. */
  async disable(user: SessionUser, currentPassword: string): Promise<void> {
    const row = await this.#prisma.user.findUnique({ where: { id: user.id } });
    if (!row) throw new NotFoundError("User not found");
    if (!(await verifyPassword(row.passwordHash, currentPassword))) {
      await this.#denials.record({
        action: "auth.mfa.disable",
        denialReason: "unauthenticated",
        targetType: "user",
        targetId: user.id,
      });
      throw new UnauthenticatedError("Invalid credentials");
    }

    const credential = await this.#prisma.mfaCredential.findUnique({ where: { userId: user.id } });
    if (!credential) throw new NotFoundError("MFA is not enabled");

    await this.#uow.runAudited(
      {
        action: "auth.mfa.disable",
        targetType: "user",
        targetId: user.id,
        outcome: "SUCCESS",
        before: { mfaEnabled: true },
        after: { mfaEnabled: false },
      },
      async (tx) => {
        await tx.mfaRecoveryCode.deleteMany({ where: { userId: user.id } });
        await tx.mfaCredential.delete({ where: { userId: user.id } });
        await tx.user.update({ where: { id: user.id }, data: { mfaEnabled: false } });
      },
    );

    // Deleting the stored secret is itself an audited SecretStore operation (§8.5). It runs
    // after the credential row is gone so a failure here cannot leave MFA half-enabled.
    await this.#secrets.delete(credential.secretName);
  }

  /**
   * Returns the accepted timestep, or `null` for an invalid **or replayed** code.
   * `lastUsedStep` is the high-water mark: equal-or-lower is a replay (§6.4).
   */
  async #verifyCode(
    secretName: string,
    email: string,
    code: string,
    lastUsedStep: bigint | null,
  ): Promise<bigint | null> {
    if (!/^\d{6}$/.test(code)) return null;

    const secretValue = await this.#secrets.get(secretName);
    const base32 = secretValue.use((plaintext) => plaintext);
    const totp = await this.#totpFor(email, base32);

    const delta = totp.validate({ token: code, window: TOTP_WINDOW });
    if (delta === null) return null;

    const currentStep = BigInt(Math.floor(Date.now() / 1000 / TOTP_PERIOD_SECONDS));
    const acceptedStep = currentStep + BigInt(delta);
    if (lastUsedStep !== null && acceptedStep <= lastUsedStep) return null;
    return acceptedStep;
  }

  /** Password hashing lives in `@sunil/db`; re-exported here only for the password change flow. */
  static hash(plaintext: string): Promise<string> {
    return hashPassword(plaintext);
  }
}
