/**
 * The secret fingerprint (§8.3, FR-042).
 *
 * `"…" + last4(plaintext) + " / sha256:" + first8hex(sha256(plaintext))`.
 *
 * This is the ONLY value-derived datum any API is permitted to return. It is computed once
 * at write time and stored, so no read path ever needs the plaintext in order to render a
 * secret in the portal.
 */
import { createHash } from "node:crypto";

export function fingerprintOf(plaintext: string): string {
  const last4 = plaintext.length <= 4 ? plaintext.slice(-1) : plaintext.slice(-4);
  const digest = createHash("sha256").update(plaintext, "utf8").digest("hex").slice(0, 8);
  return `…${last4} / sha256:${digest}`;
}
