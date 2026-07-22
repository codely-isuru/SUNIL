/**
 * The single error boundary (§9.2, FR-026, ET-3 3.3).
 *
 * Every error that escapes a handler or a guard lands here and produces:
 *  - a generic body — `{ error: <stable code> }` and nothing else. No message, no stack, no
 *    resource-existence detail, at any status code (FR-026, FR-042's error-path clause);
 *  - exactly one audit record for a DENIED request, carrying the denial category. Services
 *    that already wrote a more specific denial (login failure, MFA failure) set
 *    `denialAudited`, so a request never produces two records for one denial.
 *
 * Unknown errors become a 500 `INTERNAL`. The detail goes to the structured log with the
 * correlation id — never to the caller.
 */
import {
  Catch,
  Inject,
  type ArgumentsHost,
  type ExceptionFilter,
  type LoggerService,
} from "@nestjs/common";
import { Logger } from "@nestjs/common";
import {
  AuditWriteFailedError,
  ForbiddenError,
  InternalError,
  LockedOutError,
  NotFoundError,
  RateLimitedError,
  SunilError,
  UnauthenticatedError,
  isSunilError,
  type DenialReason,
  type ErrorCode,
} from "@sunil/core";
import type { HttpReplyLike } from "./http.types.js";
import { currentContext } from "./request-context.js";
import { isZodError, toValidationError } from "./validation.js";
import type { DenialRecorder } from "../audit/denial-recorder.js";
import { TOKENS } from "../tokens.js";

/** Denial categories that must produce a FAILURE audit record (ET-3 3.3). */
const AUDITED_DENIALS: ReadonlySet<DenialReason> = new Set([
  "unauthenticated",
  "forbidden",
  "csrf",
  "rate_limited",
  "locked_out",
  "validation",
]);

@Catch()
export class SunilExceptionFilter implements ExceptionFilter {
  readonly #logger: LoggerService = new Logger(SunilExceptionFilter.name);

  constructor(@Inject(TOKENS.DenialRecorder) private readonly denials: DenialRecorder) {}

  async catch(exception: unknown, host: ArgumentsHost): Promise<void> {
    const reply = host.switchToHttp().getResponse<HttpReplyLike>();
    const context = currentContext();

    const error = normalise(exception);
    const status = error.httpStatus;
    const body: { error: ErrorCode } = error.toPublicBody();

    if (error.denialReason && AUDITED_DENIALS.has(error.denialReason) && !context?.denialAudited) {
      try {
        await this.denials.record({
          action: "auth.denied",
          denialReason: error.denialReason,
          targetType: context?.path ?? null,
          after: { method: context?.method ?? null, code: error.code },
        });
      } catch {
        // ADR-005 §2: a failed denial record never converts into a successful request.
      }
    }

    if (status >= 500) {
      this.#logger.error?.({
        msg: "request failed",
        code: error.code,
        correlationId: context?.correlationId,
        // The message is for the log; it never reaches the caller.
        detail: error.message,
      });
    }

    if (error instanceof RateLimitedError || error instanceof LockedOutError) {
      void reply.header("Retry-After", String(error.retryAfterSeconds));
    }

    void reply.status(status).send(body);
  }
}

function normalise(exception: unknown) {
  if (isSunilError(exception)) return exception;
  if (isZodError(exception)) return toValidationError(exception);
  if (exception instanceof AuditWriteFailedError) return exception;
  if (isNestHttpException(exception)) {
    // Nest/Fastify built-ins (404, 405, payload too large) — mapped to the same generic
    // shape so the API has exactly one error vocabulary.
    const status = exception.getStatus();
    if (status === 401) return new UnauthenticatedError("Denied");
    if (status === 403) return new ForbiddenError("Denied");
    if (status === 404) return new NotFoundError("Not found");
    return new PassthroughError(status);
  }
  return new InternalError(exception instanceof Error ? exception.message : "Unknown error");
}

interface NestHttpExceptionLike {
  getStatus(): number;
}

function isNestHttpException(value: unknown): value is NestHttpExceptionLike {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as NestHttpExceptionLike).getStatus === "function"
  );
}

/** Preserves a framework status (404/405/413…) while keeping the generic body contract. */
class PassthroughError extends SunilError {
  readonly code = "INTERNAL" as const;
  readonly httpStatus: number;

  constructor(status: number) {
    super("Request could not be completed");
    this.httpStatus = status;
  }
}
