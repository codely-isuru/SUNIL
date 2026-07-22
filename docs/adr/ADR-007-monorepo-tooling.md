# ADR-007 — Monorepo tooling: pnpm workspaces + Turborepo mechanics

_Status: Accepted (confirmation + mechanics of an existing architecture decision) · Owner:
Solution Architect · Phase: 1_

## Context

`SUNIL_ARCHITECTURE.md` §1 selects pnpm workspaces + Turborepo. This ADR fixes the mechanics
Phase 1 needs: the anti-cycle rule, task pipeline, script-execution policy, and
Windows-specific hygiene (NFR-017, risk R-03). Host toolchain is confirmed: Node 22.14.0,
pnpm 11.8.0.

## Decision

- **pnpm 11 workspaces** (`apps/*`, `packages/*`) with strict isolated linking — a package
  cannot resolve an undeclared workspace dependency, which makes the dependency graph
  physically enforced, not advisory.
- **Turborepo 2** pipeline: `build` (dependsOn `^build`; `packages/db` build runs
  `prisma generate`), `typecheck`, `lint`, `lint:deps`, `test` (Vitest, JSON summary per
  workspace for FR-003), `dev` (persistent). All from the root (NFR-014).
- **Dependency DAG enforced three ways** (architecture §3.2): pnpm strict linking,
  dependency-cruiser with the allowed-edge list + `no-circular`, and TypeScript project
  references mirroring the same edges. The rule: packages import only strictly-lower
  packages; apps import packages; nothing imports apps.
- **Lifecycle scripts blocked by default** (pnpm ≥10 semantics) with an explicit
  `allowBuilds` allowlist (pnpm 11 name; formerly `onlyBuiltDependencies` — Amendment A4)
  covering `prisma`, `@prisma/engines`, `esbuild` — a supply-chain control (THREAT_MODEL
  T-16). pnpm 11's release-age gate may add `minimumReleaseAgeExclude` entries; each one is
  a Security Reviewer sign-off item.
- `.gitattributes` forces LF for container-executed files; `engine-strict=true`;
  `packageManager` field pins pnpm.

## Rejected alternatives

- **Nx.** Richer generators/graph tooling, but its plugin layer and inferred-task magic add
  a learning and audit surface a 9-workspace repo does not need; Turborepo's explicit
  `turbo.json` is easier for the security reviewer to read. The architecture doc also
  already names Turborepo.
- **Plain pnpm `-r` scripts, no orchestrator.** Works at first, but no task graph, no
  caching, no `^build` ordering — `packages/db`'s generated client ordering alone justifies
  the orchestrator.
- **moonrepo / Bazel-class tools.** Capability far beyond need; onboarding cost violates the
  NFR-013 spirit.
- **npm/yarn workspaces.** Hoisted `node_modules` defeats the physical dependency
  enforcement that pnpm's isolation gives us for free; pnpm is also the confirmed host tool.
- **ESLint `import/no-cycle` as the only cycle guard.** Kept as a fast local signal, but it
  is file-level and slow on large graphs; dependency-cruiser at package level is the
  authoritative check.

## Consequences

- The DAG is machine-checked from the first commit; an illegal import is a failed build, not
  a review comment.
- Adding a workspace package requires declaring its edges in dependency-cruiser config and
  tsconfig references — deliberate, small friction (and where Phase 3–4's
  `packages/integrations`/`packages/memory` will slot in).
- Any dependency needing a build script fails install until allowlisted — new native/build
  dependencies become visible, reviewable events.
