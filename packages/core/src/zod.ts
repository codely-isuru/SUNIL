/**
 * The single Zod entry point for the whole monorepo.
 *
 * PHASE1_ARCHITECTURE §4 / warning §18.8: `zod` is declared as a dependency of
 * `@sunil/core` and NOWHERE else. A second Zod major in the tree produces
 * structurally incompatible schema types across workspaces. Every other workspace
 * imports `z` from `@sunil/core`, and an ESLint fence (`no-restricted-imports`)
 * makes a direct `from "zod"` import a lint error outside this file.
 */
import { z } from "zod";

export { z };
export { ZodError } from "zod";
export type { ZodType, ZodTypeAny, ZodIssue, ZodSafeParseResult } from "zod";

/** Convenience alias so consumers can write `Infer<typeof Schema>`. */
export type Infer<T extends z.ZodType> = z.infer<T>;
