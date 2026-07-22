/**
 * `MockTransport` — TEST/DEV ONLY (ADR-008, FR-065).
 *
 * This module is deliberately NOT re-exported from `src/index.ts`, and `package.json` exposes
 * only the `"."` entry point, so nothing outside this package can import it. `factory.ts`
 * contains no reference to it; `factory.test.ts` asserts that no non-testing source file
 * imports from `./testing`.
 *
 * It fulfils `Transport = typeof fetch` by returning fixture `Response` objects captured from
 * PUBLISHED provider response shapes. Streaming fixtures are served as real SSE/NDJSON BYTE
 * streams so the SDKs' framing code is exercised rather than bypassed (ADR-008 consequence).
 */
import type { Transport } from "../transport.js";

export interface RecordedRequest {
  readonly url: string;
  readonly method: string;
  readonly headers: Record<string, string>;
  readonly body: unknown;
}

export interface MockRoute {
  /** Matched against the request URL with `String.includes`. */
  readonly match: string;
  readonly status?: number;
  readonly headers?: Record<string, string>;
  readonly json?: unknown;
  /** Raw body — use for SSE/NDJSON fixtures. */
  readonly body?: string;
  /** Throw instead of responding, to simulate a dead endpoint (FR-063). */
  readonly throws?: () => Error;
  /** Delay before responding, to exercise deadlines. */
  readonly delayMs?: number;
}

export class MockTransport {
  readonly requests: RecordedRequest[] = [];
  readonly #routes: MockRoute[];

  constructor(routes: MockRoute[]) {
    this.#routes = routes;
  }

  /** The injectable function. Shape-compatible with `fetch` by construction. */
  readonly fetch: Transport = async (input, init) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    const method = init?.method ?? "GET";
    const headers: Record<string, string> = {};
    new Headers(init?.headers).forEach((value, key) => {
      headers[key.toLowerCase()] = value;
    });

    let body: unknown;
    if (typeof init?.body === "string") {
      try {
        body = JSON.parse(init.body);
      } catch {
        body = init.body;
      }
    }

    this.requests.push({ url, method, headers, body });

    const route = this.#routes.find((candidate) => url.includes(candidate.match));
    if (!route) {
      return new Response(JSON.stringify({ error: { message: `no mock route for ${url}` } }), {
        status: 501,
        headers: { "content-type": "application/json" },
      });
    }

    if (route.delayMs !== undefined) {
      await new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, route.delayMs);
        init?.signal?.addEventListener("abort", () => {
          clearTimeout(timer);
          resolve();
        });
      });
    }

    if (init?.signal?.aborted) {
      throw Object.assign(new Error("The operation was aborted"), { name: "AbortError" });
    }

    if (route.throws) throw route.throws();

    if (route.body !== undefined) {
      const stream = new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(route.body));
          controller.close();
        },
      });
      return new Response(stream, {
        status: route.status ?? 200,
        headers: route.headers ?? { "content-type": "text/event-stream" },
      });
    }

    return new Response(JSON.stringify(route.json ?? {}), {
      status: route.status ?? 200,
      headers: route.headers ?? { "content-type": "application/json" },
    });
  };

  /** The last request body a fixture route received — used to assert request building. */
  lastRequest(): RecordedRequest | undefined {
    return this.requests.at(-1);
  }
}
