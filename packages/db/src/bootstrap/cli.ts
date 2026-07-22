#!/usr/bin/env node
/**
 * `pnpm db:bootstrap` entry point.
 *
 * Idempotent: run it as many times as you like. It prints a summary that names WHAT was
 * seeded and never prints a credential value.
 */
import { ConfigurationError } from "@sunil/core";
import { AuditService } from "../audit/audit-service.js";
import { createPrismaClient } from "../client.js";
import { UnitOfWork } from "../unit-of-work.js";
import { bootstrap } from "./seed.js";

async function main(): Promise<void> {
  const prisma = createPrismaClient();
  const audit = new AuditService(prisma);
  const uow = new UnitOfWork(prisma, audit);

  try {
    const report = await bootstrap({ prisma, uow });
    console.log(
      JSON.stringify(
        {
          ok: true,
          correlationId: report.correlationId,
          roles: report.rolesUpserted,
          permissions: report.permissionsUpserted,
          grantsCreated: report.grantsCreated,
          grantsRevoked: report.grantsRevoked,
          providersCreated: report.providersCreated,
          settingsCreated: report.settingsCreated,
          ownerCreated: report.ownerCreated,
          ownerEmail: report.ownerEmail,
          note: report.ownerCreated
            ? "Owner created from SUNIL_OWNER_INITIAL_PASSWORD. Change it on first login."
            : "An owner already existed; nothing was changed.",
        },
        null,
        2,
      ),
    );
  } finally {
    await prisma.$disconnect();
  }
}

main().catch((error: unknown) => {
  if (error instanceof ConfigurationError) {
    // Names the variable, never its value (FR-004).
    console.error(`bootstrap: ${error.message}`);
    console.error(`bootstrap: offending variables: ${error.variables.join(", ")}`);
  } else {
    console.error(`bootstrap failed: ${error instanceof Error ? error.message : String(error)}`);
  }
  process.exitCode = 1;
});
