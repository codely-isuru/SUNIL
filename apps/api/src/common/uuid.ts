/**
 * UUIDv7 generation.
 *
 * The schema convention is `@default(uuid(7))` (§5.1) and Prisma generates ids for us
 * everywhere EXCEPT one place: `secrets`. The envelope scheme binds the ciphertext to its
 * row with `AAD = "${secretId}:${version}"` (§8.2 / ADR-006), so the id must exist BEFORE
 * the first encryption — which means the application, not the database default, has to mint
 * it. This is the only reason this module exists; do not reach for it elsewhere.
 *
 * RFC 9562 §5.7 layout: 48-bit big-endian Unix milliseconds, 4-bit version (7), 12 bits of
 * random, 2-bit variant (0b10), 62 bits of random.
 */
import { randomBytes } from "node:crypto";

export function uuidv7(now: number = Date.now()): string {
  const bytes = randomBytes(16);

  // 48-bit timestamp, big-endian.
  bytes[0] = (now / 2 ** 40) & 0xff;
  bytes[1] = (now / 2 ** 32) & 0xff;
  bytes[2] = (now / 2 ** 24) & 0xff;
  bytes[3] = (now / 2 ** 16) & 0xff;
  bytes[4] = (now / 2 ** 8) & 0xff;
  bytes[5] = now & 0xff;

  // Version 7 in the high nibble of octet 6; variant 0b10 in the high bits of octet 8.
  bytes[6] = (bytes[6]! & 0x0f) | 0x70;
  bytes[8] = (bytes[8]! & 0x3f) | 0x80;

  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
