/**
 * Crypto helpers for the auth layer. NO primitive is hand-rolled here (ADR-003): every
 * function is a thin, named wrapper over Node's `crypto` so call sites read as intent.
 */
import { createHash, randomBytes, timingSafeEqual } from "node:crypto";

/** Opaque session/invitation token: 32 bytes of CSPRNG output, base64url (§6.1). */
export function randomToken(bytes = 32): string {
  return randomBytes(bytes).toString("base64url");
}

/** What the server stores. The raw token never touches the database (§6.1). */
export function sha256Hex(input: string): string {
  return createHash("sha256").update(input, "utf8").digest("hex");
}

/**
 * Constant-time string comparison.
 *
 * Both sides are hashed first so the comparison is over equal-length buffers — a plain
 * `timingSafeEqual` throws on a length mismatch, which would itself be an oracle for the
 * length of the expected value.
 */
export function constantTimeEquals(a: string, b: string): boolean {
  const ha = createHash("sha256").update(a, "utf8").digest();
  const hb = createHash("sha256").update(b, "utf8").digest();
  return timingSafeEqual(ha, hb);
}

const BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/**
 * MFA recovery code: 10 characters of Crockford-free RFC 4648 base32 (A–Z, 2–7), matching
 * `MfaVerifyRequestSchema` in `@sunil/core`. ~50 bits of entropy, so a SHA-256 (not argon2)
 * hash is the right storage choice (§5.2).
 */
export function randomRecoveryCode(): string {
  const source = randomBytes(10);
  let out = "";
  for (const byte of source) {
    out += BASE32_ALPHABET[byte % 32];
  }
  return out;
}
