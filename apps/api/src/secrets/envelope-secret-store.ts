/**
 * `EnvelopeSecretStore` — AES-256-GCM envelope encryption (§8.2, ADR-006, FR-040/041/044).
 *
 *   plaintext ──AES-256-GCM(DEK, iv,  AAD=`${id}:${version}`)──▶ ciphertext + authTag
 *   DEK       ──AES-256-GCM(KEK, dekIv, AAD=`${id}`)──────────▶ wrappedDek + dekAuthTag
 *
 * Three properties are worth stating because they are what the exit test checks:
 *
 *  - **Fresh 12-byte IV per encryption.** Two writes of the same plaintext therefore produce
 *    different ciphertexts, for free (ET-5 5.3).
 *  - **AAD binds ciphertext to row and version.** A ciphertext copied out of another row, or
 *    replayed from an earlier version of the same row, fails authentication. Plain GCM
 *    leaves that swap open; the AAD closes it.
 *  - **Nothing partial ever escapes.** Any tag failure throws `SecretIntegrityError` and is
 *    audited; there is no code path that returns a half-decrypted buffer (ET-5 5.9).
 *
 * The id must exist before the first encryption because it is part of the AAD, so this is
 * the one place the application mints a UUIDv7 instead of taking the database default.
 */
import { createCipheriv, createDecipheriv, randomBytes } from "node:crypto";
import {
  SecretIntegrityError,
  SecretNotFoundError,
  SecretValue,
  type SecretMetadata,
  type SecretStore,
} from "@sunil/core";
import type { Secret, SecretRepository } from "@sunil/db";
import { uuidv7 } from "../common/uuid.js";
import type { ApiConfig } from "../config/api-config.js";
import type { AuditedUnitOfWork } from "../audit/audited-unit-of-work.js";
import { fingerprintOf } from "./fingerprint.js";

const ALGORITHM = "aes-256-gcm";

/**
 * Prisma types `Bytes` columns as `Uint8Array<ArrayBuffer>`; Node hands us `Buffer`, whose
 * backing store is typed `ArrayBufferLike`. Copying into a fresh Uint8Array is the honest
 * conversion — a cast would hide a real (if theoretical) SharedArrayBuffer mismatch.
 */
function bytes(buffer: Buffer): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(buffer.byteLength);
  out.set(buffer);
  return out;
}

const IV_BYTES = 12;
const DEK_BYTES = 32;

interface Envelope {
  readonly ciphertext: Buffer;
  readonly iv: Buffer;
  readonly authTag: Buffer;
  readonly wrappedDek: Buffer;
  readonly dekIv: Buffer;
  readonly dekAuthTag: Buffer;
}

function toMetadata(row: {
  id: string;
  name: string;
  description: string;
  fingerprint: string;
  version: number;
  masterKeyVersion: number;
  rotatedAt: Date | null;
  createdAt: Date;
  updatedAt: Date;
}): SecretMetadata {
  return {
    id: row.id,
    name: row.name,
    description: row.description,
    fingerprint: row.fingerprint,
    version: row.version,
    masterKeyVersion: row.masterKeyVersion,
    rotatedAt: row.rotatedAt,
    createdAt: row.createdAt,
    updatedAt: row.updatedAt,
  };
}

export class EnvelopeSecretStore implements SecretStore {
  readonly #secrets: SecretRepository;
  readonly #uow: AuditedUnitOfWork;
  readonly #config: ApiConfig;

  constructor(secrets: SecretRepository, uow: AuditedUnitOfWork, config: ApiConfig) {
    this.#secrets = secrets;
    this.#uow = uow;
    this.#config = config;
  }

  // ── envelope primitives ───────────────────────────────────────────────────

  #seal(secretId: string, version: number, plaintext: string, kek: Buffer): Envelope {
    const dek = randomBytes(DEK_BYTES);
    const iv = randomBytes(IV_BYTES);
    const cipher = createCipheriv(ALGORITHM, dek, iv, { authTagLength: 16 });
    cipher.setAAD(Buffer.from(`${secretId}:${version}`, "utf8"));
    const ciphertext = Buffer.concat([cipher.update(plaintext, "utf8"), cipher.final()]);
    const authTag = cipher.getAuthTag();

    const dekIv = randomBytes(IV_BYTES);
    const wrapper = createCipheriv(ALGORITHM, kek, dekIv, { authTagLength: 16 });
    wrapper.setAAD(Buffer.from(secretId, "utf8"));
    const wrappedDek = Buffer.concat([wrapper.update(dek), wrapper.final()]);
    const dekAuthTag = wrapper.getAuthTag();

    // The DEK exists only for the duration of this function; it is never stored unwrapped.
    dek.fill(0);

    return { ciphertext, iv, authTag, wrappedDek, dekIv, dekAuthTag };
  }

  #unwrapDek(row: Secret, kek: Buffer): Buffer {
    const unwrapper = createDecipheriv(ALGORITHM, kek, Buffer.from(row.dekIv), {
      authTagLength: 16,
    });
    unwrapper.setAAD(Buffer.from(row.id, "utf8"));
    unwrapper.setAuthTag(Buffer.from(row.dekAuthTag));
    return Buffer.concat([unwrapper.update(Buffer.from(row.wrappedDek)), unwrapper.final()]);
  }

  #open(row: Secret, dek: Buffer): string {
    const decipher = createDecipheriv(ALGORITHM, dek, Buffer.from(row.iv), { authTagLength: 16 });
    decipher.setAAD(Buffer.from(`${row.id}:${row.version}`, "utf8"));
    decipher.setAuthTag(Buffer.from(row.authTag));
    const plaintext = Buffer.concat([
      decipher.update(Buffer.from(row.ciphertext)),
      decipher.final(),
    ]);
    const text = plaintext.toString("utf8");
    plaintext.fill(0);
    return text;
  }

  /**
   * KEK selection for a row. `SUNIL_MASTER_KEY_PREVIOUS` (implicit version −1) is what makes
   * KEK rotation possible without a bulk re-encryption event (§8.2).
   */
  #kekFor(row: Secret): { kek: Buffer; isPrevious: boolean } {
    if (row.masterKeyVersion === this.#config.masterKeyVersion) {
      return { kek: this.#config.masterKey(), isPrevious: false };
    }
    const previous = this.#config.previousMasterKey();
    if (previous && row.masterKeyVersion === this.#config.masterKeyVersion - 1) {
      return { kek: previous, isPrevious: true };
    }
    throw new SecretIntegrityError(row.name, "No master key available for this secret version");
  }

  // ── SecretStore ───────────────────────────────────────────────────────────

  /**
   * Create or replace. `put` on an existing name behaves as a rotation of the value under
   * the same reference, because that is what FR-044 requires of the reference contract.
   */
  async put(
    name: string,
    plaintext: string,
    meta: { description?: string } = {},
  ): Promise<SecretMetadata> {
    const existing = await this.#secrets.findByNameWithCiphertext(name);
    if (existing) return this.rotate(name, plaintext);

    const id = uuidv7();
    const version = 1;
    const envelope = this.#seal(id, version, plaintext, this.#config.masterKey());
    const fingerprint = fingerprintOf(plaintext);

    const row = await this.#uow.runAudited(
      (created: Secret) => ({
        action: "secret.create" as const,
        targetType: "secret",
        targetId: created.id,
        outcome: "SUCCESS" as const,
        // The NAME and the operation, never the value (§8.5, ET-5 5.11).
        after: { name: created.name, version: created.version, fingerprint: created.fingerprint },
      }),
      (tx) =>
        this.#secrets.create(tx, {
          id,
          name,
          description: meta.description ?? "",
          ciphertext: bytes(envelope.ciphertext),
          iv: bytes(envelope.iv),
          authTag: bytes(envelope.authTag),
          wrappedDek: bytes(envelope.wrappedDek),
          dekIv: bytes(envelope.dekIv),
          dekAuthTag: bytes(envelope.dekAuthTag),
          version,
          masterKeyVersion: this.#config.masterKeyVersion,
          fingerprint,
        }),
    );

    return toMetadata(row);
  }

  /**
   * Server-side read. Returns a `SecretValue` wrapper, never a string: if this ever reaches
   * a response body or a log line the marker appears, not the value (§8.4).
   */
  async get(name: string): Promise<SecretValue> {
    const row = await this.#secrets.findByNameWithCiphertext(name);
    if (!row) throw new SecretNotFoundError(name);

    let plaintext: string;
    let usedPreviousKek = false;
    try {
      const { kek, isPrevious } = this.#kekFor(row);
      usedPreviousKek = isPrevious;
      const dek = this.#unwrapDek(row, kek);
      plaintext = this.#open(row, dek);
      dek.fill(0);
    } catch (cause) {
      // Loud, typed, audited — and NOTHING partial is returned (ET-5 5.9).
      await this.#uow.recordOutOfBand({
        action: "secret.read",
        targetType: "secret",
        targetId: row.id,
        outcome: "FAILURE",
        after: { name: row.name, reason: "integrity" },
      });
      if (cause instanceof SecretIntegrityError) throw cause;
      throw new SecretIntegrityError(name);
    }

    if (usedPreviousKek) await this.#rewrapUnderCurrentKek(row, plaintext);

    // §8.5: reads are the stated exception to "mutations only" — a successful read is
    // audited after the operation, outside the read path's own transaction.
    await this.#uow.recordOutOfBand({
      action: "secret.read",
      targetType: "secret",
      targetId: row.id,
      outcome: "SUCCESS",
      after: { name: row.name, version: row.version },
    });

    return new SecretValue(name, plaintext);
  }

  /**
   * Value rotation (FR-044): new DEK, new IV, new ciphertext written OVER the old columns.
   * The previous ciphertext is retained nowhere, which is what makes it structurally
   * unretrievable rather than merely hidden. The reference name never changes.
   */
  async rotate(name: string, newPlaintext: string): Promise<SecretMetadata> {
    const existing = await this.#secrets.findByNameWithCiphertext(name);
    if (!existing) throw new SecretNotFoundError(name);

    const nextVersion = existing.version + 1;
    const envelope = this.#seal(existing.id, nextVersion, newPlaintext, this.#config.masterKey());
    const fingerprint = fingerprintOf(newPlaintext);

    const row = await this.#uow.runAudited(
      (updated: Secret) => ({
        action: "secret.rotate" as const,
        targetType: "secret",
        targetId: updated.id,
        outcome: "SUCCESS" as const,
        before: { name: existing.name, version: existing.version, fingerprint: existing.fingerprint },
        after: { name: updated.name, version: updated.version, fingerprint: updated.fingerprint },
      }),
      (tx) =>
        this.#secrets.update(tx, name, {
          ciphertext: bytes(envelope.ciphertext),
          iv: bytes(envelope.iv),
          authTag: bytes(envelope.authTag),
          wrappedDek: bytes(envelope.wrappedDek),
          dekIv: bytes(envelope.dekIv),
          dekAuthTag: bytes(envelope.dekAuthTag),
          version: nextVersion,
          masterKeyVersion: this.#config.masterKeyVersion,
          fingerprint,
          rotatedAt: new Date(),
        }),
    );

    return toMetadata(row);
  }

  async delete(name: string): Promise<void> {
    const existing = await this.#secrets.findByNameWithCiphertext(name);
    if (!existing) throw new SecretNotFoundError(name);

    await this.#uow.runAudited(
      {
        action: "secret.delete" as const,
        targetType: "secret",
        targetId: existing.id,
        outcome: "SUCCESS" as const,
        before: { name: existing.name, version: existing.version },
      },
      (tx) => this.#secrets.delete(tx, name),
    );
  }

  async describe(name: string): Promise<SecretMetadata> {
    const row = await this.#secrets.findMetadataByName(name);
    if (!row) throw new SecretNotFoundError(name);
    return toMetadata(row);
  }

  /** Metadata projection for the list endpoint — never touches ciphertext (§8.4). */
  async list(): Promise<SecretMetadata[]> {
    const rows = await this.#secrets.listMetadata();
    return rows.map(toMetadata);
  }

  countReferences(name: string): Promise<number> {
    return this.#secrets.countReferences(name);
  }

  /**
   * Lazy KEK re-wrap (§8.2): a row wrapped under the previous KEK is re-wrapped under the
   * current one on first read. Only the DEK wrapping changes — the value ciphertext, its
   * version and its fingerprint are untouched, which is why this is audited as a rotation
   * carrying an explicit `operation: kek-rewrap` marker rather than masquerading as a value
   * change.
   */
  async #rewrapUnderCurrentKek(row: Secret, plaintext: string): Promise<void> {
    const envelope = this.#seal(row.id, row.version, plaintext, this.#config.masterKey());
    await this.#uow.runAudited(
      {
        action: "secret.rotate" as const,
        targetType: "secret",
        targetId: row.id,
        outcome: "SUCCESS" as const,
        before: { name: row.name, masterKeyVersion: row.masterKeyVersion },
        after: {
          name: row.name,
          masterKeyVersion: this.#config.masterKeyVersion,
          operation: "kek-rewrap",
        },
      },
      (tx) =>
        this.#secrets.update(tx, row.name, {
          ciphertext: bytes(envelope.ciphertext),
          iv: bytes(envelope.iv),
          authTag: bytes(envelope.authTag),
          wrappedDek: bytes(envelope.wrappedDek),
          dekIv: bytes(envelope.dekIv),
          dekAuthTag: bytes(envelope.dekAuthTag),
          masterKeyVersion: this.#config.masterKeyVersion,
        }),
    );
  }
}
