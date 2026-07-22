/**
 * `InMemorySecretStore` — the FR-040 swappability proof.
 *
 * Consumers depend on the `SecretStore` interface from `@sunil/core` and nothing else, so
 * substituting this for `EnvelopeSecretStore` compiles and passes unchanged. It is a TEST
 * DOUBLE: it holds plaintext in a Map and is never wired into a running service.
 */
import {
  SecretNotFoundError,
  SecretValue,
  type SecretMetadata,
  type SecretStore,
} from "@sunil/core";
import { uuidv7 } from "../common/uuid.js";
import { fingerprintOf } from "./fingerprint.js";

interface Entry {
  readonly id: string;
  readonly name: string;
  description: string;
  plaintext: string;
  version: number;
  rotatedAt: Date | null;
  readonly createdAt: Date;
  updatedAt: Date;
}

export class InMemorySecretStore implements SecretStore {
  readonly #entries = new Map<string, Entry>();

  #metadata(entry: Entry): SecretMetadata {
    return {
      id: entry.id,
      name: entry.name,
      description: entry.description,
      fingerprint: fingerprintOf(entry.plaintext),
      version: entry.version,
      masterKeyVersion: 1,
      rotatedAt: entry.rotatedAt,
      createdAt: entry.createdAt,
      updatedAt: entry.updatedAt,
    };
  }

  async put(
    name: string,
    plaintext: string,
    meta: { description?: string } = {},
  ): Promise<SecretMetadata> {
    const now = new Date();
    const existing = this.#entries.get(name);
    if (existing) {
      existing.plaintext = plaintext;
      existing.description = meta.description ?? existing.description;
      existing.version += 1;
      existing.updatedAt = now;
      return this.#metadata(existing);
    }
    const entry: Entry = {
      id: uuidv7(),
      name,
      description: meta.description ?? "",
      plaintext,
      version: 1,
      rotatedAt: null,
      createdAt: now,
      updatedAt: now,
    };
    this.#entries.set(name, entry);
    return this.#metadata(entry);
  }

  async get(name: string): Promise<SecretValue> {
    const entry = this.#entries.get(name);
    if (!entry) throw new SecretNotFoundError(name);
    return new SecretValue(name, entry.plaintext);
  }

  async rotate(name: string, newPlaintext: string): Promise<SecretMetadata> {
    const entry = this.#entries.get(name);
    if (!entry) throw new SecretNotFoundError(name);
    entry.plaintext = newPlaintext;
    entry.version += 1;
    entry.rotatedAt = new Date();
    entry.updatedAt = entry.rotatedAt;
    return this.#metadata(entry);
  }

  async delete(name: string): Promise<void> {
    if (!this.#entries.delete(name)) throw new SecretNotFoundError(name);
  }

  async describe(name: string): Promise<SecretMetadata> {
    const entry = this.#entries.get(name);
    if (!entry) throw new SecretNotFoundError(name);
    return this.#metadata(entry);
  }
}
