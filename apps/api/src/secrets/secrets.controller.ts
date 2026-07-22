/**
 * `/api/secrets` — §8.4 enforcement layer 2, at the route level.
 *
 * Every response on this controller is a `SecretMetadata` DTO: id, name, description,
 * fingerprint, version, key version, timestamps. That list is exhaustive and it is
 * allowlisted at the repository level too (`SECRET_METADATA_SELECT` in `@sunil/db`), so a
 * value cannot reach a response even by a careless `select`.
 *
 * There is deliberately NO read-value endpoint. `secret:read` grants metadata only — no
 * permission string exists that returns a secret value, because no API returns one (§7.1).
 */
import { Body, Controller, Delete, Get, HttpCode, Inject, Param, Post } from "@nestjs/common";
import { ApiOperation, ApiTags } from "@nestjs/swagger";
import {
  ConflictError,
  NotFoundError,
  SecretCreateSchema,
  SecretRotateSchema,
  UuidSchema,
  type SecretStore,
} from "@sunil/core";
import type { SecretRepository } from "@sunil/db";
import { Audited, Idempotent, RequiresPermission } from "../common/declarations.js";
import { parseInput } from "../common/validation.js";
import { TOKENS } from "../tokens.js";
import type { EnvelopeSecretStore } from "./envelope-secret-store.js";

@ApiTags("secrets")
@Controller("secrets")
export class SecretsController {
  constructor(
    @Inject(TOKENS.SecretStore) private readonly secrets: SecretStore,
    @Inject(TOKENS.SecretRepository) private readonly repository: SecretRepository,
  ) {}

  @Post()
  @RequiresPermission("secret:create")
  @Audited("secret.create")
  @Idempotent()
  @HttpCode(201)
  @ApiOperation({ summary: "Store a secret. The response carries metadata only." })
  async create(@Body() body: unknown) {
    const input = parseInput(SecretCreateSchema, body);
    const existing = await this.repository.findMetadataByName(input.name);
    if (existing) throw new ConflictError("A secret with that name already exists");
    return this.secrets.put(input.name, input.value, { description: input.description });
  }

  @Get()
  @RequiresPermission("secret:read")
  async list() {
    return { items: await (this.secrets as EnvelopeSecretStore).list() };
  }

  @Get(":id")
  @RequiresPermission("secret:read")
  async get(@Param("id") id: string) {
    const name = await this.#nameFor(id);
    return this.secrets.describe(name);
  }

  @Post(":id/rotate")
  @RequiresPermission("secret:rotate")
  @Audited("secret.rotate")
  @HttpCode(200)
  @ApiOperation({ summary: "Replace the value behind a reference; the reference is unchanged" })
  async rotate(@Param("id") id: string, @Body() body: unknown) {
    const input = parseInput(SecretRotateSchema, body);
    const name = await this.#nameFor(id);
    return this.secrets.rotate(name, input.value);
  }

  @Delete(":id")
  @RequiresPermission("secret:delete")
  @Audited("secret.delete")
  @HttpCode(200)
  async remove(@Param("id") id: string) {
    const name = await this.#nameFor(id);
    // A secret referenced by a provider or an MFA credential may not be deleted (§13) —
    // otherwise the reference would dangle and fail at call time inside an adapter.
    if ((await this.repository.countReferences(name)) > 0) {
      throw new ConflictError("Secret is referenced and cannot be deleted");
    }
    await this.secrets.delete(name);
    return { ok: true };
  }

  /** Routes address secrets by id; the store addresses them by name. */
  async #nameFor(id: string): Promise<string> {
    const parsed = parseInput(UuidSchema, id);
    const all = await (this.secrets as EnvelopeSecretStore).list();
    const found = all.find((row) => row.id === parsed);
    if (!found) throw new NotFoundError("Secret not found");
    return found.name;
  }
}
