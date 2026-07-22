/**
 * Structured logging (NFR-011).
 *
 * ONE redaction list feeds both logs and audit payloads: `PINO_REDACT_PATHS` comes from
 * `@sunil/core`, the same module the audit service redacts with, so the two cannot diverge.
 * Every job log line carries a correlation id (NFR-012).
 */
import pino, { type Logger } from "pino";
import { PINO_REDACT_PATHS, REDACTED } from "@sunil/core";

export type AppLogger = Logger;

export function createLogger(name: string, level: pino.LevelWithSilent = "info"): AppLogger {
  return pino({
    name,
    level,
    redact: { paths: [...new Set(PINO_REDACT_PATHS)], censor: REDACTED },
    base: { service: name },
  });
}
