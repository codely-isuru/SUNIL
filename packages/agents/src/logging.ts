/**
 * The logging seam for the agent runtime.
 *
 * `packages/agents` owns no logging stack (`no-console` is a lint error here); apps inject a
 * Pino child logger already configured with `PINO_REDACT_PATHS`. Structurally compatible
 * with Pino, so `logger.child({ agentId })` can be passed straight in.
 */
export interface AgentLogger {
  debug(context: Record<string, unknown>, message: string): void;
  info(context: Record<string, unknown>, message: string): void;
  warn(context: Record<string, unknown>, message: string): void;
  error(context: Record<string, unknown>, message: string): void;
}

export const NOOP_AGENT_LOGGER: AgentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};
