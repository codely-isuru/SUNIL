/**
 * `@sunil/api` — process entry point.
 *
 * The non-negotiables the scaffold laid down are satisfied structurally, not by convention:
 *
 *  1. Prisma comes from `@sunil/db` (the guarded client) — `@prisma/client` is unreachable
 *     from this app by lint fence, dependency-cruiser rule and pnpm strict linking.
 *  2. Every mutation goes through `AuditedUnitOfWork` → `UnitOfWork.runAudited`; there is no
 *     `$transaction` call anywhere in `apps/api`.
 *  3. Default deny is enforced by `SessionGuard` at run time and by the route-enumeration
 *     test at build time (§7.4).
 *  4. Permission strings come from the `@sunil/core` catalogue; none is minted here.
 *  5. Configuration is validated at process start and the process refuses to run without it.
 *  6. Registration endpoints do not exist.
 *  7. Zod is imported from `@sunil/core`.
 */
import { Logger } from "@nestjs/common";
import { ConfigurationError } from "@sunil/core";
import { createApiApp } from "./app.factory.js";
import { ApiConfig } from "./config/api-config.js";
import { buildOpenApiDocument } from "./openapi.js";

export { createApiApp } from "./app.factory.js";
export { ApiConfig } from "./config/api-config.js";
export { AppModule, API_CONTROLLERS, type ApiModuleOptions } from "./app.module.js";
export { buildOpenApiDocument } from "./openapi.js";

export interface ApiBootstrapResult {
  readonly port: number;
}

/**
 * Configuration-only preflight. Kept as a separate exported function because it is the
 * cheapest possible proof of FR-004 — it fails naming the variable, without opening a
 * socket or a database connection.
 */
export function prepareApiBootstrap(env: NodeJS.ProcessEnv = process.env): ApiBootstrapResult {
  return { port: ApiConfig.load(env).port };
}

export async function bootstrap(): Promise<void> {
  const logger = new Logger("bootstrap");
  const config = ApiConfig.load();

  const app = await createApiApp({ config });

  // Generation is exercised at boot so a decorator mistake surfaces on start rather than in
  // a later phase. The document is not served (see `openapi.ts`).
  const document = buildOpenApiDocument(app);
  logger.log(`OpenAPI document generated: ${Object.keys(document.paths ?? {}).length} paths`);

  await app.listen({ port: config.port, host: "0.0.0.0" });
  logger.log(`SUNIL API listening on port ${config.port}`);
}

/**
 * `require.main === module` rather than a top-level call: importing this module from a test
 * or a tool must never start a server.
 */
if (require.main === module) {
  bootstrap().catch((error: unknown) => {
    const logger = new Logger("bootstrap");
    if (error instanceof ConfigurationError) {
      // Names the offending variables; never prints a value (FR-004).
      logger.error(`Refusing to start: ${error.message} [${error.variables.join(", ")}]`);
    } else {
      logger.error(`Refusing to start: ${error instanceof Error ? error.message : "unknown"}`);
    }
    process.exitCode = 1;
  });
}
