/**
 * Security headers and CSP (§6.7, FR-031, NFR-004).
 *
 * Applied by a Fastify `onSend` hook so EVERY response carries them — including error
 * responses and the 404s Fastify produces before Nest sees the request.
 *
 * The API serves JSON, not documents, so its own CSP is the maximally restrictive form:
 * `default-src 'none'`. The portal's CSP (script/style/font/connect sources, per-request
 * nonce) is set by `apps/web`'s Next middleware — the same policy text, applied where the
 * documents actually are. Both are stated in §6.7; this file owns the API half.
 */
export interface SecurityHeaderOptions {
  /** `Strict-Transport-Security` is only meaningful — and only set — over HTTPS. */
  readonly secure: boolean;
}

export function securityHeaders(options: SecurityHeaderOptions): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Security-Policy": [
      "default-src 'none'",
      "frame-ancestors 'none'",
      "object-src 'none'",
      "base-uri 'none'",
      "form-action 'none'",
    ].join("; "),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    // Auth responses are never cacheable; applying it uniformly avoids a per-route mistake.
    "Cache-Control": "no-store",
  };
  if (options.secure) {
    headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains";
  }
  return headers;
}
