import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "api",
    environment: "node",
    include: ["src/**/*.test.ts"],
    passWithNoTests: true,
    reporters: ["default", "json"],
    outputFile: { json: ".vitest/results.json" },
    // The e2e suites share ONE Postgres and each resets it. Running files in parallel makes
    // two TRUNCATEs race and deadlock — the failure is an artefact of the harness, not of the
    // code under test, so the files run one at a time.
    fileParallelism: false,
    testTimeout: 60_000,
    hookTimeout: 60_000,
  },
});
