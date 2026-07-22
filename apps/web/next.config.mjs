/**
 * Next 15 configuration for the SUNIL portal.
 *
 * Deliberately small. Every knob here is a decision recorded in PHASE1_ARCHITECTURE §14 or
 * §6.7; anything not needed to satisfy those is left at Next's default.
 *
 * @type {import('next').NextConfig}
 */
const nextConfig = {
  reactStrictMode: true,

  // `@sunil/ui` is a workspace package compiled by `tsc` to CommonJS. Transpiling it here means
  // Next owns the final output for both the server and the client bundle, and the "use client"
  // directives in its component files are honoured consistently.
  transpilePackages: ["@sunil/ui"],

  // ADR-011 / amendment A1 — SAME-ORIGIN, NO CORS.
  //
  // The browser never talks to the API origin. Every client-side fetch is a RELATIVE
  // `/api/...` path, and this rewrite proxies it to the API over the private network, so
  // there is no cross-origin request to configure CORS for anywhere in Phase 1.
  //
  // `SUNIL_API_INTERNAL_URL` is SERVER-SIDE ONLY and never reaches the browser bundle. The
  // public API-URL variable was removed from the configuration inventory by A1: with
  // same-origin relative paths, no API origin belongs in client code at all.
  async rewrites() {
    const internal = process.env.SUNIL_API_INTERNAL_URL ?? "http://localhost:3001";
    return [{ source: "/api/:path*", destination: `${internal.replace(/\/$/, "")}/api/:path*` }];
  },

  // `sharp` is DENIED in the install allowlist (pnpm-workspace.yaml), and Phase 1 ships no
  // raster imagery — the entire visual system is canvas, SVG and CSS. Disabling the optimiser
  // keeps the build from ever asking for it.
  images: { unoptimized: true },

  // Security headers are set in `src/middleware.ts`, not here, because the CSP carries a
  // per-request nonce (§6.7) and a static header cannot.
  poweredByHeader: false,

  // PORTAL_SHELL_SPEC.md §7 names `/sign-in` and `/sign-in/mfa`; PHASE1_ARCHITECTURE §14 names
  // `/login` and `/mfa` for the same screens. The design spec is implemented and the
  // architecture's paths redirect onto it, so a link written against either document works.
  async redirects() {
    return [
      { source: "/login", destination: "/sign-in", permanent: false },
      { source: "/mfa", destination: "/sign-in/mfa", permanent: false },
    ];
  },
};

export default nextConfig;
