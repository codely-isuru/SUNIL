/**
 * Password hashing — argon2id via `@node-rs/argon2` (ADR-003, §4).
 *
 * Warning §18.1: do NOT substitute the node-gyp `argon2` package. `@node-rs/argon2` ships
 * prebuilt N-API binaries for win32-x64 and linux-x64-musl, which is why installs work on a
 * Windows host with no native toolchain. Any node-gyp dependency requires a new ADR.
 *
 * Primitives are never hand-rolled here: this file only chooses parameters.
 */
import { randomBytes } from "node:crypto";
import { Algorithm, hash, verify } from "@node-rs/argon2";

/**
 * OWASP-recommended argon2id parameters (19 MiB, t=2, p=1). Stored inside the PHC string,
 * so a future parameter change does not invalidate existing hashes.
 */
export const ARGON2_OPTIONS = {
  algorithm: Algorithm.Argon2id,
  memoryCost: 19_456,
  timeCost: 2,
  parallelism: 1,
} as const;

export function hashPassword(plaintext: string): Promise<string> {
  return hash(plaintext, ARGON2_OPTIONS);
}

export async function verifyPassword(phcHash: string, plaintext: string): Promise<boolean> {
  try {
    return await verify(phcHash, plaintext, ARGON2_OPTIONS);
  } catch {
    // A malformed stored hash must not be distinguishable from a wrong password.
    return false;
  }
}

let dummyHash: Promise<string> | undefined;

/**
 * Timing equalisation for the login path (§6.3 step 3, FR-022): when no user row matches the
 * submitted email, verify against this instead of returning early, so response time carries
 * no account-existence oracle.
 *
 * It is generated at first use from fresh randomness — no hash constant is committed to the
 * repository and no password is recoverable from it.
 */
export function getDummyPasswordHash(): Promise<string> {
  dummyHash ??= hashPassword(randomBytes(32).toString("base64"));
  return dummyHash;
}
