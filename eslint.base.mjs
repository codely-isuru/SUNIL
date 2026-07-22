// Shared ESLint 9 flat-config factory.
//
// Each workspace has a three-line `eslint.config.mjs` that calls this with its role, so all
// `files`/`ignores` patterns stay relative to the workspace being linted (flat config
// resolves them against the cwd) while the RULES live in exactly one place.
//
// The interesting content is the "fences" — the lint rules named in PHASE1_ARCHITECTURE
// §7.4 / §8.5 / §9.4 / §18. They are not style preferences; each one guards a structural
// property the security reviewer is going to check.
import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

/** Imports that are banned everywhere, in every workspace, with no exemption. */
const ALWAYS_BANNED_IMPORTS = [
  {
    name: "argon2",
    message:
      "Use `@node-rs/argon2` (prebuilt N-API binaries). The node-gyp `argon2` package drags a native toolchain onto Windows — §4/§18.1. Adding any node-gyp dependency requires a new ADR.",
  },
  {
    name: "node-gyp",
    message: "Native build tooling is banned in Phase 1 (§18.1). Adding one requires an ADR.",
  },
];

const ZOD_BAN = {
  name: "zod",
  message:
    "Import `z` from `@sunil/core`, which is the single declared Zod dependency. A second Zod major splits schema types across workspaces — §4/§18.8.",
};

const PRISMA_CLIENT_BAN = {
  name: "@prisma/client",
  message:
    "Import the client from `@sunil/db`. The exported client carries the audit append-only guard; the raw client is deliberately not exported — §18.6.",
};

const AUDIT_LOG_FENCE = {
  selector: "MemberExpression[property.name='auditLog']",
  message:
    "`audit_logs` is reached only through `AuditService` in `@sunil/db`, so timestamps and redaction cannot be bypassed — §9.4.",
};

const TRANSACTION_FENCE = {
  selector: "MemberExpression[property.name='$transaction']",
  message:
    "Never call `prisma.$transaction` ad hoc for a mutation. Use `UnitOfWork.runAudited` — an ad-hoc transaction is not covered by audit-before-commit — §18.2 / ADR-005.",
};

const DANGEROUS_HTML_FENCE = {
  selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
  message: "`dangerouslySetInnerHTML` is banned in Phase 1 — FR-031.",
};

const BULLMQ_REPEAT_FENCE = {
  selector: "Property[key.name='repeat'][value.type='ObjectExpression']",
  message:
    "The legacy BullMQ `repeat` option is BANNED — its option-derived keys silently duplicate schedule definitions. Use `queue.upsertJobScheduler(<stable id>, …)` — ADR-010 / §18.3.",
};

const BASE_IGNORES = [
  "dist/**",
  "build/**",
  ".next/**",
  ".turbo/**",
  "coverage/**",
  ".vitest/**",
  "node_modules/**",
  "**/*.d.ts",
];

/**
 * @param {object} options
 * @param {"core"|"db"|"ui"|"web"|"node-app"|"scheduler-app"|"root"} options.role
 */
export function createEslintConfig({ role }) {
  const restrictedImports = [...ALWAYS_BANNED_IMPORTS];
  if (role !== "core") restrictedImports.push(ZOD_BAN);
  if (role !== "db") restrictedImports.push(PRISMA_CLIENT_BAN);

  const restrictedSyntax = [TRANSACTION_FENCE, DANGEROUS_HTML_FENCE];
  if (role !== "db") restrictedSyntax.push(AUDIT_LOG_FENCE);
  if (role === "scheduler-app" || role === "node-app") restrictedSyntax.push(BULLMQ_REPEAT_FENCE);

  const browserish = role === "ui" || role === "web";

  const config = [
    { ignores: BASE_IGNORES },
    js.configs.recommended,
    ...tseslint.configs.recommended,
    {
      languageOptions: {
        ecmaVersion: 2023,
        sourceType: "module",
        globals: browserish ? { ...globals.node, ...globals.browser } : { ...globals.node },
      },
      linterOptions: { reportUnusedDisableDirectives: "error" },
      rules: {
        "no-console": "error",
        "no-restricted-imports": ["error", { paths: restrictedImports }],
        "no-restricted-syntax": ["error", ...restrictedSyntax],
        "@typescript-eslint/no-unused-vars": [
          "error",
          { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrors: "none" },
        ],
        "@typescript-eslint/consistent-type-imports": [
          "error",
          { prefer: "type-imports", fixStyle: "separate-type-imports" },
        ],
        eqeqeq: ["error", "smart"],
        "no-eval": "error",
        "no-implied-eval": "error",
        "no-new-func": "error",
      },
    },
  ];

  if (role === "core") {
    // This one file IS the sanctioned Zod re-export.
    config.push({
      files: ["src/zod.ts"],
      rules: { "no-restricted-imports": ["error", { paths: ALWAYS_BANNED_IMPORTS }] },
    });
  }

  if (role === "db") {
    // Inside `@sunil/db` the finer fences apply: only AuditService may touch `auditLog`,
    // and only the UnitOfWork may open a transaction.
    config.push({
      files: ["src/**/*.ts"],
      ignores: ["src/audit/**", "src/__tests__/**", "src/unit-of-work.ts"],
      rules: {
        "no-restricted-syntax": ["error", AUDIT_LOG_FENCE, TRANSACTION_FENCE],
      },
    });
    config.push({
      files: ["src/unit-of-work.ts"],
      rules: { "no-restricted-syntax": ["error", AUDIT_LOG_FENCE] },
    });
    config.push({
      files: ["src/bootstrap/cli.ts"],
      rules: { "no-console": "off" },
    });
  }

  // Test sources may drive the guarded surfaces directly — that is what they exist to prove.
  config.push({
    files: ["src/**/__tests__/**/*.ts", "src/**/*.test.ts", "src/**/*.test.tsx"],
    rules: {
      "no-console": "off",
      "no-restricted-syntax": "off",
      "@typescript-eslint/no-explicit-any": "off",
    },
  });

  return config;
}
