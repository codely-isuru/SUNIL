/**
 * The application factory — ONE assembly path for the process and for every test.
 *
 * Everything that is not a Nest concept is wired here as a Fastify hook, because the two
 * things that must be true for EVERY response (the request context and the security
 * headers) have to hold for responses Nest never sees: framework 404s, body-parse failures,
 * and anything short-circuited before the router.
 */
import { NestFactory } from "@nestjs/core";
import { FastifyAdapter, type NestFastifyApplication } from "@nestjs/platform-fastify";
import { Logger } from "nestjs-pino";
import { randomUUID } from "node:crypto";
import { AppModule, type ApiModuleOptions } from "./app.module.js";
import { ANONYMOUS_ACTOR, runWithContext, type RequestContext } from "./common/request-context.js";
import { securityHeaders } from "./common/security-headers.js";
import {
  headerValue,
  type HttpReplyLike,
  type HttpRequestLike,
  type HttpServerLike,
} from "./common/http.types.js";

export const API_PREFIX = "api";

export interface ApiAppHooks {
  /**
   * Called for every route Fastify registers. The route-enumeration test uses this to obtain
   * the REGISTERED route table — the second, independent input to the §7.4 check, so a route
   * that never went through a controller decorator still cannot hide from it.
   */
  readonly onRoute?: (route: { method: string; path: string }) => void;
}

export async function createApiApp(
  options: ApiModuleOptions,
  hooks: ApiAppHooks = {},
): Promise<NestFastifyApplication> {
  /**
   * Fastify's own request id IS the correlation id. Setting it here rather than in the Pino
   * options means ONE value flows through the request context, the audit records and every
   * structured log line — which is exactly what NFR-012 asks for and what ET-3 3.8 checks.
   */
  const adapter = new FastifyAdapter({
    trustProxy: false,
    bodyLimit: 1_048_576,
    genReqId: (request: { headers: Record<string, string | string[] | undefined> }) =>
      headerValue(request.headers, "x-correlation-id") ?? `req-${randomUUID()}`,
  });
  const instance = adapter.getInstance() as unknown as HttpServerLike;

  const headers = securityHeaders({ secure: options.config.cookieSecure });

  if (hooks.onRoute) {
    const collect = hooks.onRoute;
    (instance as unknown as { addHook(name: string, handler: (route: { method: string | string[]; url: string }) => void): unknown }).addHook(
      "onRoute",
      (route) => {
        const methods = Array.isArray(route.method) ? route.method : [route.method];
        for (const method of methods) collect({ method, path: route.url });
      },
    );
  }

  /**
   * The request context wraps the ENTIRE downstream chain. `done()` is invoked inside
   * `runWithContext`, so every hook, guard, interceptor and handler that follows runs inside
   * the same AsyncLocalStorage store — which is what makes the correlation id and the audit
   * tally reachable without threading them through every signature.
   */
  instance.addHook("onRequest", (request: HttpRequestLike, reply: HttpReplyLike, done: () => void) => {
    const correlationId =
      request.id ?? headerValue(request.headers, "x-correlation-id") ?? `req-${randomUUID()}`;
    void reply.header("x-correlation-id", correlationId);

    const context: RequestContext = {
      correlationId,
      method: request.method,
      path: request.url,
      ip: request.ip || null,
      userAgent: headerValue(request.headers, "user-agent") ?? null,
      actor: ANONYMOUS_ACTOR,
      session: null,
      permissions: null,
      declaration: null,
      auditAction: null,
      auditWrites: 0,
      denialAudited: false,
      idempotentReplay: false,
    };

    runWithContext(context, () => done());
  });

  instance.addHook(
    "onSend",
    (
      _request: HttpRequestLike,
      reply: HttpReplyLike,
      payload: unknown,
      done: (error: Error | null, payload?: unknown) => void,
    ) => {
      for (const [name, value] of Object.entries(headers)) {
        void reply.header(name, value);
      }
      done(null, payload);
    },
  );

  // Unmatched routes are Nest's own `NotFoundException`, which the global exception filter
  // renders in the same generic vocabulary as everything else — so a probe for a
  // registration endpoint learns nothing from the shape of the reply (FR-020, ET-1 1.1).
  // Registering a Fastify-level 404 handler here would collide with Nest's.

  const app = await NestFactory.create<NestFastifyApplication>(
    AppModule.register(options),
    adapter,
    { bufferLogs: true },
  );

  app.setGlobalPrefix(API_PREFIX);
  app.useLogger(app.get(Logger));
  app.enableShutdownHooks();

  await app.init();
  return app;
}
