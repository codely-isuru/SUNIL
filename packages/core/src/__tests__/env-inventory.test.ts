/**
 * FR-092 — `.env.example` and code stay in lockstep.
 *
 * `ENV_VAR_NAMES` in `@sunil/core` is the canonical §16 inventory; `.env.example` is the
 * operator-facing documentation of the same list. Nothing kept them honest until now, and
 * they had already drifted: ADR-011 removed `NEXT_PUBLIC_API_URL` and added
 * `SUNIL_API_INTERNAL_URL`, `.env.example` was updated, and this file was not.
 *
 * `.env.example` is owned by the DevOps engineer. This test READS it and never writes it.
 * It carries an explicitly delimited "compose-only" section for variables the Postgres image
 * and the Compose files need that are NOT part of §16 (they are consumed by containers, not
 * by application code); the boundary is taken from that marker rather than guessed, so the
 * two sections can evolve independently without this test going soft.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import {
  DELIBERATELY_ABSENT_ENV_VAR_NAMES,
  ENV_VAR_NAMES,
  SECRET_ENV_VAR_NAMES,
} from "../config.js";

const ENV_EXAMPLE_PATH = resolve(process.cwd(), "../../.env.example");
const COMPOSE_ONLY_MARKER = /^#\s*Compose-only variables/im;

function readEnvExample(): string {
  try {
    return readFileSync(ENV_EXAMPLE_PATH, "utf8");
  } catch {
    throw new Error(
      `FR-092: .env.example not found at ${ENV_EXAMPLE_PATH}. Every variable read by the code must be documented there.`,
    );
  }
}

/** `NAME=` at the start of a line, ignoring comments. Returns [name, rawValue]. */
function declaredAssignments(source: string): Map<string, string> {
  const out = new Map<string, string>();
  for (const line of source.split(/\r?\n/)) {
    const match = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/.exec(line);
    if (match?.[1] !== undefined) out.set(match[1], (match[2] ?? "").trim());
  }
  return out;
}

const source = readEnvExample();
const composeOnlyIndex = source.search(COMPOSE_ONLY_MARKER);
const inventorySection =
  composeOnlyIndex === -1 ? source : source.slice(0, composeOnlyIndex);
const composeOnlySection = composeOnlyIndex === -1 ? "" : source.slice(composeOnlyIndex);

const inventoryVars = declaredAssignments(inventorySection);
const composeOnlyVars = declaredAssignments(composeOnlySection);

describe("FR-092 — .env.example matches the §16 inventory in code", () => {
  it("delimits its compose-only section explicitly", () => {
    // If this marker is ever removed, the boundary below becomes a guess — fail loudly here
    // rather than silently treating container variables as part of §16.
    expect(composeOnlyIndex).toBeGreaterThan(-1);
    expect(composeOnlyVars.size).toBeGreaterThan(0);
  });

  it("documents every variable the code reads", () => {
    const missing = ENV_VAR_NAMES.filter((name) => !inventoryVars.has(name));
    expect(missing, `undocumented in .env.example: ${missing.join(", ")}`).toEqual([]);
  });

  it("declares no §16 variable the code does not read", () => {
    const known = new Set<string>(ENV_VAR_NAMES);
    const extra = [...inventoryVars.keys()].filter((name) => !known.has(name));
    expect(
      extra,
      `present in .env.example but absent from ENV_VAR_NAMES — add it to §16/core or move it to the compose-only section: ${extra.join(", ")}`,
    ).toEqual([]);
  });

  it("keeps the ADR-011 absences absent from both sections", () => {
    for (const name of DELIBERATELY_ABSENT_ENV_VAR_NAMES) {
      expect(ENV_VAR_NAMES as readonly string[]).not.toContain(name);
      expect(inventoryVars.has(name), `${name} is deliberately absent (ADR-011)`).toBe(false);
      expect(composeOnlyVars.has(name), `${name} is deliberately absent (ADR-011)`).toBe(false);
    }
  });

  it("carries the ADR-011 replacement", () => {
    expect(ENV_VAR_NAMES as readonly string[]).toContain("SUNIL_API_INTERNAL_URL");
    expect(inventoryVars.has("SUNIL_API_INTERNAL_URL")).toBe(true);
  });

  it("ships no real value for any secret-shaped variable (NFR-005)", () => {
    for (const name of SECRET_ENV_VAR_NAMES) {
      const value = inventoryVars.get(name);
      expect(value, `${name} must be documented`).toBeDefined();
      expect(value, `${name} must carry no value in the committed template`).toBe("");
    }
  });

  it("contains no credential-shaped literal anywhere in the file", () => {
    expect(source).not.toMatch(/\bsk-[A-Za-z0-9_-]{16,}/);
    expect(source).not.toMatch(/-----BEGIN [A-Z ]*PRIVATE KEY-----/);
    // A populated connection string would mean a real host/credential leaked into the template.
    expect(source).not.toMatch(/^DATABASE_URL=\S+/m);
    expect(source).not.toMatch(/^REDIS_URL=\S+/m);
  });
});
