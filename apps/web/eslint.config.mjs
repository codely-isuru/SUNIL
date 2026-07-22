import { createEslintConfig } from "../../eslint.base.mjs";

/**
 * The same two fences `packages/ui` carries, applied to the app (see that file for why the
 * shared selectors are repeated rather than extended):
 *
 *   1. no `toLocale*String` without an explicit `timeZone` — the A-10 defect, made
 *      un-writable rather than merely documented (PORTAL_SHELL_SPEC.md §6.1);
 *   2. no colour literal anywhere in `apps/web` (FR-100: "no brand colour is hard-coded as a
 *      literal outside the token definitions", and the token definitions are in
 *      `packages/ui`, so this workspace has NO exception at all).
 */
const NO_LOCALE_WITHOUT_TIMEZONE = {
  selector:
    "CallExpression[callee.property.name=/^toLocale(Date|Time)?String$/]:not(:has(ObjectExpression > Property[key.name='timeZone']))",
  message:
    "Never format a date without an explicit `timeZone` from the resolved setting — that is the inherited `Australia/Melbourne` defect (A-10, PORTAL_SHELL_SPEC §6). Use `@sunil/ui`'s time helpers, which take the zone from `<TimeZoneProvider>`.",
};

const NO_COLOUR_LITERAL = {
  selector: "Literal[value=/^(#[0-9a-fA-F]{3,8}|rgba?\\(|hsla?\\()/]",
  message:
    "No colour literal in `apps/web` (FR-100). Reference a `--sunil-*` token, or import the value from `@sunil/ui` if a non-CSS surface such as `themeColor` needs it.",
};

/* Repeated from eslint.base.mjs so adding a fence cannot silently drop one. */
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
  ...createEslintConfig({ role: "web" }),
  {
    files: ["src/**/*.ts", "src/**/*.tsx"],
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
    files: ["src/**/__tests__/**/*.ts", "src/**/__tests__/**/*.tsx"],
    rules: { "no-restricted-syntax": "off" },
  },
];
