/**
 * The logging seam.
 *
 * `packages/llm` owns no logging stack (Pino lives in the apps, and `no-console` is a lint
 * error here). Consumers inject anything structurally compatible with Pino; the apps inject
 * a Pino child logger already configured with `PINO_REDACT_PATHS`.
 *
 * Nothing in this package logs a prompt, a completion or a credential.
 */
export interface LlmLogger {
  debug(context: Record<string, unknown>, message: string): void;
  info(context: Record<string, unknown>, message: string): void;
  warn(context: Record<string, unknown>, message: string): void;
  error(context: Record<string, unknown>, message: string): void;
}

/** Discards everything. The default, so a caller that supplies no logger is silent, not noisy. */
export const NOOP_LLM_LOGGER: LlmLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};
