/**
 * Minimal structural types for the HTTP layer.
 *
 * `fastify` is a transitive dependency of `@nestjs/platform-fastify`, not a declared
 * dependency of `apps/api` — and under pnpm's strict linking an undeclared import does not
 * resolve, which is the fence working as designed (§3.2). Rather than declare a dependency
 * this app does not own, the handful of members actually used are described structurally.
 *
 * The upside is not only fence compliance: guards and interceptors typed against this
 * interface are testable with a plain object, so the security-critical paths do not need a
 * live server to unit-test.
 */
export interface HttpRequestLike {
  readonly method: string;
  readonly url: string;
  readonly ip?: string;
  /** Fastify's request id. Configured to BE the correlation id (§9.1, NFR-012). */
  readonly id?: string;
  readonly headers: Record<string, string | string[] | undefined>;
}

export interface HttpReplyLike {
  header(name: string, value: string): unknown;
  status(code: number): HttpReplyLike;
  send(payload: unknown): unknown;
}

/** The subset of the Fastify instance the factory drives. */
export interface HttpServerLike {
  addHook(name: "onRequest", handler: OnRequestHook): unknown;
  addHook(name: "onSend", handler: OnSendHook): unknown;
  setNotFoundHandler(handler: (request: HttpRequestLike, reply: HttpReplyLike) => void): unknown;
}

export type OnRequestHook = (
  request: HttpRequestLike,
  reply: HttpReplyLike,
  done: () => void,
) => void;

export type OnSendHook = (
  request: HttpRequestLike,
  reply: HttpReplyLike,
  payload: unknown,
  done: (error: Error | null, payload?: unknown) => void,
) => void;

export function headerValue(
  headers: Record<string, string | string[] | undefined>,
  name: string,
): string | undefined {
  const raw = headers[name];
  return Array.isArray(raw) ? raw[0] : raw;
}
