/**
 * ET-4 4.10 — "grep the codebase for scheduled work relying solely on setTimeout/setInterval:
 * zero occurrences as a sole mechanism".
 *
 * A grep in a checklist rots. This is the grep with teeth: every timer in the four workspaces
 * this task owns must appear in the allowlist below WITH a justification, and the allowlist
 * may only contain timers that CANCEL work or that live inside an already-running job. A new
 * timer anywhere in `packages/llm`, `packages/agents`, `apps/worker` or `apps/scheduler` fails
 * this test until someone writes down why it is not a scheduling mechanism.
 *
 * (Scope: the workspaces owned by this task. The repo-wide grep across `apps/api`,
 * `packages/ui` and `apps/web` belongs to the QA evidence pack, not to a test that would break
 * whenever another workstream edits its own files.)
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, resolve, sep } from "node:path";
import { describe, expect, it } from "vitest";

const REPO_ROOT = resolve(process.cwd(), "..", "..");

const OWNED_WORKSPACES = [
  join("packages", "llm"),
  join("packages", "agents"),
  join("apps", "worker"),
  join("apps", "scheduler"),
];

/**
 * The ONLY sanctioned timers, each with the reason it is not "scheduled work".
 * Keys are repo-relative POSIX paths.
 */
const SANCTIONED_TIMERS: Readonly<Record<string, string>> = {
  "packages/agents/src/heartbeat.ts":
    "§11.3 — the heartbeat interval INSIDE an already-running job. Staleness detection itself is the durable out-of-process `system:agent-staleness-sweep` repeatable, not this timer.",
  "packages/llm/src/transport.ts":
    "§11.4 — an AbortController deadline for an in-flight LLM call. It CANCELS work; it never schedules any.",
  "apps/worker/src/worker.ts":
    "FR-081 — the handler-level deadline that classifies an overrunning job as TIMED_OUT. It cancels work; it never schedules any.",
  "packages/llm/src/testing/mock-transport.ts":
    "Test/dev fixture only: a simulated response delay so adapter deadlines can be exercised.",
};

const TIMER_PATTERN = /\b(setInterval|setTimeout)\s*\(/;

function collectSources(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      // Tests may use timers freely — they are not the running system.
      if (entry === "__tests__" || entry === "node_modules" || entry === "dist") continue;
      collectSources(full, found);
    } else if (entry.endsWith(".ts") && !entry.endsWith(".test.ts")) {
      found.push(full);
    }
  }
  return found;
}

describe("ET-4 4.10 — no setTimeout/setInterval is the sole mechanism for scheduled work", () => {
  const offenders = OWNED_WORKSPACES.flatMap((workspace) =>
    collectSources(join(REPO_ROOT, workspace, "src")),
  )
    .filter((file) => TIMER_PATTERN.test(readFileSync(file, "utf8")))
    .map((file) => relative(REPO_ROOT, file).split(sep).join("/"));

  it("finds no timer outside the sanctioned, justified list", () => {
    const unsanctioned = offenders.filter((file) => !(file in SANCTIONED_TIMERS));
    expect(unsanctioned).toEqual([]);
  });

  it("keeps the allowlist honest — every entry still exists and still contains a timer", () => {
    expect(offenders.sort()).toEqual(Object.keys(SANCTIONED_TIMERS).sort());
  });

  it("schedules nothing in the scheduler app itself: it upserts definitions and idles", () => {
    const main = readFileSync(join(REPO_ROOT, "apps", "scheduler", "src", "main.ts"), "utf8");
    expect(TIMER_PATTERN.test(main)).toBe(false);
    // And it produces only — a scheduler that constructed a Worker would be consuming.
    expect(main).not.toMatch(/new\s+Worker\s*\(/);
    expect(main).toMatch(/upsertJobScheduler|registerSchedulers/);
  });
});
