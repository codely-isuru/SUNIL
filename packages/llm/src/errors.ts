/**
 * The provider error taxonomy (§10.3, FR-061/062/063).
 *
 * RAW TRANSPORT ERRORS NEVER ESCAPE AN ADAPTER. Every adapter wraps its work in
 * `toProviderError(slug, cause)`, which maps SDK errors, fetch failures, abort/timeout
 * signals and malformed payloads onto `ProviderError` from `@sunil/core` with one of the six
 * classes. `usage_records.errorClass` uses the same union, so a failed call and its usage row
 * cannot disagree.
 *
 * Messages are scrubbed with the shared redaction module before they leave this file: a
 * provider error body can echo a request header, and that header can be an API key.
 */
import {
  ProviderError,
  SecretIntegrityError,
  SecretNotFoundError,
  ValidationError,
  ZodError,
  scrubString,
  type ProviderErrorClass,
  type ProviderSlug,
} from "@sunil/core";

export interface Classification {
  readonly errorClass: ProviderErrorClass;
  readonly retryable: boolean;
}

/** HTTP status → taxonomy. Retryability is a property of the class, decided here once. */
export function classifyStatus(status: number): Classification {
  if (status === 401 || status === 403) return { errorClass: "auth", retryable: false };
  if (status === 408) return { errorClass: "timeout", retryable: true };
  if (status === 429) return { errorClass: "rate_limit", retryable: true };
  if (status >= 500) return { errorClass: "server", retryable: true };
  // 400/404/409/413/422 and friends: we sent something the provider would not accept, or the
  // endpoint is not what we think it is. Retrying an identical request cannot help.
  return { errorClass: "contract", retryable: false };
}

const MAX_MESSAGE = 2000;

function safeMessage(value: unknown): string {
  const raw =
    value instanceof Error ? value.message : typeof value === "string" ? value : "provider call failed";
  return scrubString(raw).slice(0, MAX_MESSAGE);
}

function nameOf(value: unknown): string {
  return value instanceof Error ? value.name : "";
}

function statusOf(value: unknown): number | undefined {
  if (typeof value !== "object" || value === null) return undefined;
  const status = (value as { status?: unknown }).status;
  return typeof status === "number" && Number.isFinite(status) ? status : undefined;
}

function isAbort(value: unknown): boolean {
  const name = nameOf(value);
  return name === "AbortError" || name === "APIUserAbortError" || name === "TimeoutError";
}

function isConnectionError(value: unknown): boolean {
  const name = nameOf(value);
  if (name === "APIConnectionError" || name === "FetchError") return true;
  // Node's undici surfaces a plain `TypeError: fetch failed` with the real reason on `cause`.
  return value instanceof TypeError && /fetch failed|network|ECONN|ENOTFOUND|EAI_AGAIN/i.test(safeMessage(value));
}

/**
 * Map anything thrown inside an adapter onto the typed taxonomy.
 *
 * Ordering matters: an SDK timeout error is both an abort and a connection error, and must
 * classify as `timeout`.
 */
export function toProviderError(provider: ProviderSlug, cause: unknown): ProviderError {
  if (cause instanceof ProviderError) return cause;

  // Our own boundary validation failed on the RESPONSE — that is contract drift, which is
  // exactly the R-01 failure mode this taxonomy exists to make visible.
  if (cause instanceof ZodError || cause instanceof ValidationError) {
    return new ProviderError({
      provider,
      errorClass: "contract",
      retryable: false,
      message: `response did not match the expected shape: ${safeMessage(cause)}`,
      cause,
    });
  }

  // The credential could not be resolved from the SecretStore, or failed its integrity
  // check. Nothing was sent, and no retry can help until an operator fixes the secret — the
  // `auth` class describes it accurately on both the error and the usage row.
  if (cause instanceof SecretNotFoundError || cause instanceof SecretIntegrityError) {
    return new ProviderError({
      provider,
      errorClass: "auth",
      retryable: false,
      message: `credential '${cause.secretName}' could not be resolved`,
      cause,
    });
  }

  if (nameOf(cause) === "APIConnectionTimeoutError" || isAbort(cause)) {
    return new ProviderError({
      provider,
      errorClass: "timeout",
      retryable: true,
      message: safeMessage(cause),
      cause,
    });
  }

  const status = statusOf(cause);
  if (status !== undefined) {
    const { errorClass, retryable } = classifyStatus(status);
    return new ProviderError({ provider, errorClass, retryable, message: safeMessage(cause), status, cause });
  }

  if (isConnectionError(cause)) {
    return new ProviderError({
      provider,
      errorClass: "connectivity",
      retryable: true,
      message: safeMessage(cause),
      cause,
    });
  }

  return new ProviderError({
    provider,
    errorClass: "server",
    retryable: false,
    message: safeMessage(cause),
    cause,
  });
}

/**
 * Request-side validation failure. Distinct from a provider error: we never sent anything, so
 * there is nothing to classify as the provider's fault — but a usage row is still written by
 * the recorder, with `errorClass: 'contract'`.
 */
export function toValidationError(error: unknown, context: string): ValidationError {
  if (error instanceof ZodError) {
    return new ValidationError(
      `${context} failed validation`,
      error.issues.map((issue) => issue.path.join(".") || "<root>"),
      { cause: error },
    );
  }
  return new ValidationError(`${context} failed validation`, [], { cause: error });
}
