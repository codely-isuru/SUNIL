/**
 * §8.4 enforcement layer 2 — the serialisation interceptor.
 *
 * `SecretValue.toJSON()` already yields `"[REDACTED]"`, so a leak would degrade to a marker
 * rather than a plaintext. That is not good enough: a redaction marker in a response body
 * means a developer wired a secret into a DTO and nobody noticed. So this interceptor walks
 * every outgoing response object and **throws** if a `SecretValue` instance appears
 * anywhere in it.
 *
 * The failure mode is deliberately loud and server-side. There is no configuration to turn
 * it off.
 */
import {
  Injectable,
  type CallHandler,
  type ExecutionContext,
  type NestInterceptor,
} from "@nestjs/common";
import { InternalError, isSecretValue } from "@sunil/core";
import { map, type Observable } from "rxjs";

const MAX_DEPTH = 12;

export function assertNoSecretValue(value: unknown, depth = MAX_DEPTH, seen = new WeakSet<object>()): void {
  if (value === null || value === undefined || depth <= 0) return;
  if (isSecretValue(value)) {
    throw new InternalError("A SecretValue reached a response boundary");
  }
  if (typeof value !== "object") return;
  if (seen.has(value as object)) return;
  seen.add(value as object);

  if (Array.isArray(value)) {
    for (const item of value) assertNoSecretValue(item, depth - 1, seen);
    return;
  }
  for (const item of Object.values(value as Record<string, unknown>)) {
    assertNoSecretValue(item, depth - 1, seen);
  }
}

@Injectable()
export class SecretSerialisationInterceptor implements NestInterceptor {
  intercept(_context: ExecutionContext, next: CallHandler): Observable<unknown> {
    return next.handle().pipe(
      map((value) => {
        assertNoSecretValue(value);
        return value;
      }),
    );
  }
}
