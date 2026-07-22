/**
 * dependency-cruiser — the authoritative machine check of the dependency DAG
 * (PHASE1_ARCHITECTURE §3.2 enforcement layer 2, ADR-007).
 *
 *         core            (depends on: zod only)
 *        ↙  |  ↘
 *      db  llm  ui        (db → core; llm → core, db; ui → core [types/tokens only])
 *         ↘ |
 *         agents          (agents → core, db, llm)
 *           |
 *    apps/{web,api,worker,scheduler}
 *
 * A package may import only packages strictly BELOW it. Apps may import any package.
 * NOTHING imports from `apps/*`.
 *
 * Run AFTER a build: workspace packages resolve through their `exports` map to `dist/`, so
 * `pnpm build && pnpm lint:deps` is the correct order (the root `pnpm check` script does
 * this). The `not-to-unresolvable` rule makes a stale/absent build loud rather than silent.
 */
module.exports = {
  forbidden: [
    {
      name: "no-circular",
      severity: "error",
      comment:
        "A cycle between workspaces or modules. The DAG is acyclic by construction; a cycle means an edge was added in the wrong direction.",
      from: {},
      to: { circular: true },
    },
    {
      name: "not-to-unresolvable",
      severity: "error",
      comment:
        "An import that cannot be resolved. Usually means the workspace packages have not been built (`pnpm build`) — which would otherwise make the DAG rules silently pass.",
      from: { path: "^(apps|packages)/" },
      to: { couldNotResolve: true },
    },
    {
      name: "packages-do-not-import-apps",
      severity: "error",
      comment: "Nothing in `packages/*` may import from `apps/*` (§3.2).",
      from: { path: "^packages/" },
      to: { path: "^apps/" },
    },
    {
      name: "apps-do-not-import-other-apps",
      severity: "error",
      comment:
        "An app may import packages, never another app. `apps/web` talks to `apps/api` over HTTP, not by import (§3.1/§3.2).",
      from: { path: "^apps/([^/]+)/" },
      to: { path: "^apps/", pathNot: "^apps/$1/" },
    },
    {
      name: "core-depends-on-nothing",
      severity: "error",
      comment:
        "`packages/core` sits at the bottom of the DAG: zod only, no workspace dependencies (§3.1).",
      from: { path: "^packages/core/" },
      to: { path: "^packages/(db|llm|ui|agents)/" },
    },
    {
      name: "db-depends-on-core-only",
      severity: "error",
      comment: "`packages/db` may import `core` and nothing else in the workspace (§3.2).",
      from: { path: "^packages/db/" },
      to: { path: "^packages/(llm|ui|agents)/" },
    },
    {
      name: "llm-depends-on-core-and-db",
      severity: "error",
      comment: "`packages/llm` may import `core` and `db` only (§3.2).",
      from: { path: "^packages/llm/" },
      to: { path: "^packages/(ui|agents)/" },
    },
    {
      name: "agents-may-not-import-ui",
      severity: "error",
      comment: "`packages/agents` may import `core`, `db` and `llm` — never `ui` (§3.2).",
      from: { path: "^packages/agents/" },
      to: { path: "^packages/ui/" },
    },
    {
      name: "ui-depends-on-core-only",
      severity: "error",
      comment:
        "`packages/ui` may import `core` only — never `db`, `llm` or `agents`; it has no data fetching and no API knowledge (§3.1).",
      from: { path: "^packages/ui/" },
      to: { path: "^packages/(db|llm|agents)/" },
    },
    {
      name: "ui-core-import-is-types-and-tokens-only",
      severity: "error",
      comment:
        "`packages/ui` may reach `@sunil/core` ONLY through the `/types` and `/tokens` subpaths. Design tokens must not drag server schemas (or Zod) into the client bundle (§3.2).",
      from: { path: "^packages/ui/" },
      to: { path: "^packages/core/(?!dist/(types|tokens))" },
    },
    {
      name: "web-holds-no-server-data-layer",
      severity: "error",
      comment:
        "`apps/web` holds no secrets and no database access: its only configuration is the API base URL, and `SecretStore.get` must not even be compilable here (§14, §8.4 fence 4).",
      from: { path: "^apps/web/" },
      to: { path: "^packages/(db|agents)/" },
    },
    {
      name: "prisma-client-only-in-db",
      severity: "error",
      comment:
        "Apps and other packages import the GUARDED client from `@sunil/db`, never `@prisma/client` directly — the raw client has no audit append-only guard (§18.6).",
      from: { pathNot: "^packages/db/" },
      to: { path: "node_modules/@prisma/client/" },
    },
    {
      name: "zod-only-in-core",
      severity: "error",
      comment:
        "Zod is declared in `@sunil/core` and re-exported. A second Zod major in the tree produces incompatible schema types across workspaces (§18.8).",
      from: { pathNot: "^packages/core/" },
      to: { path: "node_modules/zod/" },
    },
    {
      name: "no-node-gyp-argon2",
      severity: "error",
      comment:
        "`@node-rs/argon2` only. The node-gyp `argon2` package breaks Windows installs (§4/§18.1); adding any node-gyp dependency requires a new ADR.",
      from: {},
      to: { path: "node_modules/argon2/" },
    },
    {
      name: "prototype-is-read-only",
      severity: "error",
      comment:
        "`prototype/` is read-only design reference (FR-001). No Phase 1 code imports from it; tokens are EXTRACTED, files untouched.",
      from: { path: "^(apps|packages)/" },
      to: { path: "^prototype/" },
    },
  ],
  options: {
    // `doNotFollow`, NOT `exclude`: node_modules and the compiled `dist/` of a workspace
    // package must still appear in the graph as leaf nodes, otherwise every cross-workspace
    // edge disappears and the DAG rules below become vacuous. We simply do not crawl INTO
    // them. (The cruise targets are `*/src`, so dist files are never entry points.)
    doNotFollow: { path: "(^|/)(node_modules|dist)(/|$)" },
    exclude: {
      // Tooling config (eslint/vitest/turbo) is not part of the application graph, and its
      // resolver quirks must not be able to masquerade as a DAG violation.
      path: "(^|/)(\\.next|\\.turbo|coverage|\\.vitest)(/|$)|\\.config\\.(ts|mjs|cjs|js)$|eslint\\.base\\.mjs$",
    },
    tsPreCompilationDeps: true,
    combinedDependencies: false,
    baseDir: ".",
    enhancedResolveOptions: {
      // Required so the `@sunil/core/types` and `@sunil/core/tokens` SUBPATH exports resolve;
      // without it the ui→core fence below could never fire. "import" must be in the
      // condition list because several dev dependencies are ESM-only.
      exportsFields: ["exports"],
      conditionNames: ["node", "import", "require", "types", "default"],
      mainFields: ["main", "module", "types"],
    },
    reporterOptions: {
      text: { highlightFocused: true },
    },
  },
};
