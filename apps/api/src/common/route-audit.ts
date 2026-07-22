/**
 * §7.4 layer 2 and §9.4 — default deny and audit coverage as a NAMED BUILD FAILURE.
 *
 * Layer 1 (the guard) makes an undeclared route return 403 at run time. That is necessary
 * but not sufficient: an undeclared route would still ship, and the failure would only be
 * discovered by whoever called it. This module is layer 2 — it walks the controllers, pairs
 * them with the routes Fastify actually registered, and returns a list of violations that
 * NAME the offending route.
 *
 * Two independent inputs are compared on purpose:
 *  - the DECLARED set, read from Nest's own `path`/`method` metadata on the controllers;
 *  - the REGISTERED set, collected from Fastify's `onRoute` hook.
 * A route that exists in the server but has no declared counterpart is itself a violation,
 * so a handler registered by a route that never went through a controller decorator cannot
 * hide from this check.
 */
import { RequestMethod, type Type } from "@nestjs/common";
import { METHOD_METADATA, PATH_METADATA } from "@nestjs/common/constants";
import { readAuditActions, readDeclarations, type RouteDeclaration } from "./declarations.js";

export interface DeclaredRoute {
  readonly controller: string;
  readonly handler: string;
  readonly method: string;
  readonly path: string;
  readonly declarations: readonly RouteDeclaration[];
  readonly auditActions: readonly string[];
}

export interface RouteViolation {
  readonly route: string;
  readonly problem: string;
}

const METHOD_NAMES: Record<number, string> = {
  [RequestMethod.GET]: "GET",
  [RequestMethod.POST]: "POST",
  [RequestMethod.PUT]: "PUT",
  [RequestMethod.DELETE]: "DELETE",
  [RequestMethod.PATCH]: "PATCH",
  [RequestMethod.ALL]: "ALL",
  [RequestMethod.OPTIONS]: "OPTIONS",
  [RequestMethod.HEAD]: "HEAD",
};

const MUTATING = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function joinPath(...parts: string[]): string {
  const joined = parts
    .flatMap((part) => part.split("/"))
    .filter((segment) => segment.length > 0 && segment !== "/")
    .join("/");
  return `/${joined}`;
}

/** Enumerate every handler on every controller, with its declaration metadata. */
export function describeControllerRoutes(
  controllers: readonly Type<unknown>[],
  globalPrefix: string,
): DeclaredRoute[] {
  const routes: DeclaredRoute[] = [];

  for (const controller of controllers) {
    const controllerPath = (Reflect.getMetadata(PATH_METADATA, controller) as string | undefined) ?? "";
    const prototype = controller.prototype as Record<string, unknown>;

    for (const name of Object.getOwnPropertyNames(prototype)) {
      if (name === "constructor") continue;
      const handler = prototype[name];
      if (typeof handler !== "function") continue;

      const methodCode = Reflect.getMetadata(METHOD_METADATA, handler) as number | undefined;
      const routePath = Reflect.getMetadata(PATH_METADATA, handler) as string | undefined;
      if (methodCode === undefined || routePath === undefined) continue;

      routes.push({
        controller: controller.name,
        handler: name,
        method: METHOD_NAMES[methodCode] ?? `UNKNOWN(${methodCode})`,
        path: joinPath(globalPrefix, controllerPath, routePath),
        declarations: readDeclarations(handler as object),
        auditActions: readAuditActions(handler as object),
      });
    }
  }

  return routes;
}

/**
 * The rules, stated once:
 *   R1 every route carries EXACTLY ONE of @Public / @SelfService / @RequiresPermission
 *   R2 every POST/PUT/PATCH/DELETE route carries @Audited with exactly one action
 *   R3 every route Fastify registered corresponds to a declared route
 */
export function findDeclarationViolations(
  routes: readonly DeclaredRoute[],
  registered: readonly { method: string; path: string }[] = [],
): RouteViolation[] {
  const violations: RouteViolation[] = [];

  for (const route of routes) {
    const label = `${route.method} ${route.path} (${route.controller}.${route.handler})`;

    if (route.declarations.length === 0) {
      violations.push({
        route: label,
        problem:
          "carries no access declaration — add exactly one of @Public(), @SelfService() or @RequiresPermission() (§7.4)",
      });
    } else if (route.declarations.length > 1) {
      violations.push({
        route: label,
        problem: `carries ${route.declarations.length} access declarations — exactly one is allowed (§7.4)`,
      });
    }

    if (MUTATING.has(route.method)) {
      if (route.auditActions.length === 0) {
        violations.push({
          route: label,
          problem: "is a mutating route with no @Audited action (§9.4)",
        });
      } else if (route.auditActions.length > 1) {
        violations.push({
          route: label,
          problem: `declares ${route.auditActions.length} @Audited actions — exactly one is allowed (§9.4)`,
        });
      }
    }
  }

  const declaredKeys = new Set(routes.map((route) => `${route.method} ${normalise(route.path)}`));
  for (const route of registered) {
    const key = `${route.method} ${normalise(route.path)}`;
    if (!declaredKeys.has(key)) {
      violations.push({
        route: `${route.method} ${route.path}`,
        problem: "is registered on the server but has no declared controller handler (§7.4)",
      });
    }
  }

  return violations;
}

/** Fastify renders parameters as `:id`; Nest metadata uses the same form, so only trailing
 * slashes need normalising. */
function normalise(path: string): string {
  const trimmed = path.replace(/\/+$/, "");
  return trimmed.length > 0 ? trimmed : "/";
}

export function formatViolations(violations: readonly RouteViolation[]): string {
  return violations.map((v) => `  • ${v.route} — ${v.problem}`).join("\n");
}
