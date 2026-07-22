/**
 * OpenAPI generation (§13).
 *
 * The document is GENERATED but not SERVED. Phase 1 has no consumer for a live spec
 * endpoint, and mounting Swagger UI would add routes that carry no §7.4 declaration —
 * which the route-enumeration test would (correctly) fail. Generation is exercised at
 * boot and asserted by `openapi.test.ts`, which is where FR-020's "no registration
 * operation in the document" is proved.
 */
import { DocumentBuilder, SwaggerModule } from "@nestjs/swagger";
import type { INestApplication } from "@nestjs/common";
import type { OpenAPIObject } from "@nestjs/swagger";

export function buildOpenApiDocument(app: INestApplication): OpenAPIObject {
  const config = new DocumentBuilder()
    .setTitle("SUNIL API")
    .setDescription(
      "Phase 1 foundation API. Invitation-only: there is no registration operation, by design (FR-020).",
    )
    .setVersion("0.1.0")
    .addCookieAuth("sunil_session", { type: "apiKey", in: "cookie" })
    .build();

  return SwaggerModule.createDocument(app, config);
}

/** Operation shapes that must never appear in the document (FR-020). */
export const FORBIDDEN_OPERATION_PATTERNS: readonly RegExp[] = [
  /register/i,
  /signup/i,
  /sign-up/i,
  /create-account/i,
];

/**
 * FR-020's document check, applied to PATHS and OPERATION IDS only.
 *
 * Deliberately not a substring scan of the whole document: the description legitimately
 * explains that no registration operation exists, and a naive scan would flag the sentence
 * that documents the requirement being satisfied.
 */
export function findForbiddenOperations(document: OpenAPIObject): string[] {
  const offenders: string[] = [];

  for (const [path, item] of Object.entries(document.paths ?? {})) {
    for (const pattern of FORBIDDEN_OPERATION_PATTERNS) {
      if (pattern.test(path)) offenders.push(`path ${path} matches ${String(pattern)}`);
    }
    for (const [method, operation] of Object.entries(item as Record<string, unknown>)) {
      const operationId = (operation as { operationId?: string } | undefined)?.operationId;
      if (!operationId) continue;
      for (const pattern of FORBIDDEN_OPERATION_PATTERNS) {
        if (pattern.test(operationId)) {
          offenders.push(`operation ${method.toUpperCase()} ${path} (${operationId})`);
        }
      }
    }
  }

  return offenders;
}
