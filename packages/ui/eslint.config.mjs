import { createEslintConfig } from "../../eslint.base.mjs";

/**
 * Two extra fences for this workspace, on top of the shared ones.
 *
 * `no-restricted-syntax` is a single rule name, so a later config object REPLACES the array
 * rather than adding to it. The two shared selectors from `eslint.base.mjs` are therefore
 * repeated verbatim below — losing `dangerouslySetInnerHTML` (FR-031) while adding a fence of
 * my own would be a poor trade, and a test in `__tests__` is not what catches it: ESLint is.
 *
 * FENCE 1 — the time-zone rule (PORTAL_SHELL_SPEC.md §6.1). "No component may call
 * `toLocaleString` / `toLocaleTimeString` / `toLocaleDateString` without an explicit
 * `timeZone` argument… This is a lint-enforceable rule and should be enforced, not trusted."
 *
 * FENCE 2 — no colour literal outside the token definitions (FR-100, and the Gate 2 rgba ban
 * on the JavaScript side, where `css-contract.ts` cannot see). `tokens.ts` is the one
 * sanctioned exception: it IS the token definition.
 */
const NO_LOCALE_WITHOUT_TIMEZONE = {
  selector:
    "CallExpression[callee.property.name=/^toLocale(Date|Time)?String$/]:not(:has(ObjectExpression > Property[key.name='timeZone']))",
  message:
    "Never format a date without an explicit `timeZone` from the resolved setting — that is the inherited `Australia/Melbourne` defect (A-10, PORTAL_SHELL_SPEC §6). Use the helpers in `time/timezone.ts`.",
};

const NO_COLOUR_LITERAL = {
  selector: "Literal[value=/^(#[0-9a-fA-F]{3,8}|rgba?\\(|hsla?\\()/]",
  message:
    "No colour literal outside `tokens/tokens.ts` (FR-100). Use a `--sunil-*` token; alpha colours may never be a text colour at all (Gate 2).",
};

/* Repeated from eslint.base.mjs — see the note above. */
const SHARED_TRANSACTION_FENCE = {
  selector: "MemberExpression[property.name='$transaction']",
  message:
    "Never call `prisma.$transaction` ad hoc for a mutation. Use `UnitOfWork.runAudited` — an ad-hoc transaction is not covered by audit-before-commit — §18.2 / ADR-005.",
};
const SHARED_DANGEROUS_HTML_FENCE = {
  selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
  message: "`dangerouslySetInnerHTML` is banned in Phase 1 — FR-031.",
};
const SHARED_AUDIT_LOG_FENCE = {
  selector: "MemberExpression[property.name='auditLog']",
  message:
    "`audit_logs` is reached only through `AuditService` in `@sunil/db`, so timestamps and redaction cannot be bypassed — §9.4.",
};

export default [
  ...createEslintConfig({ role: "ui" }),
  {
    files: ["src/**/*.ts", "src/**/*.tsx"],
    ignores: ["src/tokens/tokens.ts"],
    rules: {
      "no-restricted-syntax": [
        "error",
        SHARED_TRANSACTION_FENCE,
        SHARED_DANGEROUS_HTML_FENCE,
        SHARED_AUDIT_LOG_FENCE,
        NO_LOCALE_WITHOUT_TIMEZONE,
        NO_COLOUR_LITERAL,
      ],
    },
  },
  {
    // Tests may write the violations they exist to reject.
    files: ["src/**/__tests__/**/*.ts", "src/**/__tests__/**/*.tsx"],
    rules: { "no-restricted-syntax": "off" },
  },
];
