/**
 * Route declarations — §7.4 default deny, made structural.
 *
 * Every handler carries EXACTLY ONE of `@Public()`, `@SelfService()` or
 * `@RequiresPermission()`, and every mutating handler additionally carries `@Audited()`.
 *
 * Note the deliberate choice NOT to use Nest's `SetMetadata`: `SetMetadata` overwrites, so
 * a handler carrying two declarations would look like one and the "exactly one" rule could
 * never be tested. These decorators APPEND to an array, so a double declaration is visible
 * — and both the runtime guard and the route-enumeration test reject it.
 */
import "reflect-metadata";
import type { AuditAction, PermissionKey } from "@sunil/core";

export const DECLARATION_METADATA = "sunil:route-declaration";
export const AUDITED_METADATA = "sunil:route-audited";
export const AUTH_ENDPOINT_METADATA = "sunil:route-auth-endpoint";
export const IDEMPOTENT_METADATA = "sunil:route-idempotent";

export type RouteDeclaration =
  | { readonly kind: "public" }
  | { readonly kind: "self-service" }
  | { readonly kind: "permission"; readonly permission: PermissionKey };

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- decorator targets are untyped by design
type DecoratorTarget = any;

function appendMetadata(key: string, value: unknown) {
  return (target: DecoratorTarget, _propertyKey?: string | symbol, descriptor?: PropertyDescriptor) => {
    const subject: object = descriptor ? (descriptor.value as object) : (target as object);
    const existing = (Reflect.getOwnMetadata(key, subject) as unknown[] | undefined) ?? [];
    Reflect.defineMetadata(key, [...existing, value], subject);
    return descriptor ?? target;
  };
}

/** On the explicit allowlist: login, MFA verify, invitation accept, health (§7.4). */
export const Public = (): MethodDecorator =>
  appendMetadata(DECLARATION_METADATA, { kind: "public" }) as MethodDecorator;

/** Requires an ACTIVE session and acts only on the caller's own account (§7.4). */
export const SelfService = (): MethodDecorator =>
  appendMetadata(DECLARATION_METADATA, { kind: "self-service" }) as MethodDecorator;

/** Requires the named permission from the `@sunil/core` catalogue — never a minted string. */
export const RequiresPermission = (permission: PermissionKey): MethodDecorator =>
  appendMetadata(DECLARATION_METADATA, { kind: "permission", permission }) as MethodDecorator;

/** The audit action a mutating handler is expected to produce (§9.4). */
export const Audited = (action: AuditAction): MethodDecorator =>
  appendMetadata(AUDITED_METADATA, action) as MethodDecorator;

/** Marks a route as subject to the stricter per-IP auth rate limit (§6.3 step 1). */
export const AuthEndpoint = (): MethodDecorator =>
  appendMetadata(AUTH_ENDPOINT_METADATA, true) as MethodDecorator;

/** Honours an `Idempotency-Key` header by replaying the first response. */
export const Idempotent = (): MethodDecorator =>
  appendMetadata(IDEMPOTENT_METADATA, true) as MethodDecorator;

export function readDeclarations(handler: object): readonly RouteDeclaration[] {
  return (Reflect.getMetadata(DECLARATION_METADATA, handler) as RouteDeclaration[] | undefined) ?? [];
}

export function readAuditActions(handler: object): readonly AuditAction[] {
  return (Reflect.getMetadata(AUDITED_METADATA, handler) as AuditAction[] | undefined) ?? [];
}

export function hasMarker(handler: object, key: string): boolean {
  const values = Reflect.getMetadata(key, handler) as unknown[] | undefined;
  return Array.isArray(values) && values.length > 0;
}

/**
 * Resolve the single declaration for a handler.
 *
 * `null` means "not declared" — and the guard turns that into a 403 before the handler
 * runs. Absence of a declaration is denial, not exposure (§7.4 layer 1).
 */
export function resolveDeclaration(handler: object): RouteDeclaration | null {
  const declarations = readDeclarations(handler);
  return declarations.length === 1 ? declarations[0]! : null;
}
