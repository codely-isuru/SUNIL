import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "scheduler",
    environment: "node",
    include: ["src/**/*.test.ts"],
    passWithNoTests: true,
    reporters: ["default", "json"],
    outputFile: { json: ".vitest/results.json" },
    // The integration specs drive the SAME real `system` queue and stop/start real
    // containers. Running the files in parallel would have them fight each other, so they
    // run serially — a flaky ET-4 is worse than a slow one (risk R-04).
    fileParallelism: false,
    testTimeout: 240_000,
    hookTimeout: 60_000,
  },
});
