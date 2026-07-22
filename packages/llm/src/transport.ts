/**
 * The transport seam (§10.2, ADR-008).
 *
 * The injectable unit is `fetch` itself. Anthropic and OpenAI adapters hand this function to
 * their official SDKs; the Ollama adapter calls it directly. Tests inject a `MockTransport`
 * (`src/testing/`, never exported from the package root) so the whole suite runs with ZERO
 * API keys.
 *
 * The production factory constructs `REAL_FETCH_TRANSPORT` unconditionally — there is no
 * configuration value, env var or profile that can substitute a mock (FR-065).
 */

/** `Transport = typeof fetch`. Nothing narrower: the SDKs expect a drop-in fetch. */
export type Transport = typeof fetch;

/**
 * The one and only production transport. Wrapped rather than aliased so `globalThis.fetch`
 * is resolved per call (Node's fetch is lazily installed) and so `this` is never bound.
 */
export const REAL_FETCH_TRANSPORT: Transport = (input, init) => globalThis.fetch(input, init);

/**
 * Compose an `AbortSignal` that fires at the request deadline (§11.4: in-flight LLM calls
 * carry an AbortController deadline). Returns the signal and a disposer the caller MUST run
 * in a `finally`, so a completed request does not leave a pending timer behind.
 */
export function deadlineSignal(
  timeoutMs: number,
  external?: AbortSignal,
): { signal: AbortSignal; dispose: () => void } {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort(new Error(`deadline of ${timeoutMs}ms exceeded`));
  }, timeoutMs);

  const onExternalAbort = (): void => controller.abort(external?.reason);
  if (external) {
    if (external.aborted) controller.abort(external.reason);
    else external.addEventListener("abort", onExternalAbort, { once: true });
  }

  return {
    signal: controller.signal,
    dispose: () => {
      clearTimeout(timer);
      external?.removeEventListener("abort", onExternalAbort);
    },
  };
}
