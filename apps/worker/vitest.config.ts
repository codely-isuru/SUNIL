import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "worker",
    environment: "node",
    include: ["src/**/*.test.ts"],
    passWithNoTests: true,
    reporters: ["default", "json"],
    outputFile: { json: ".vitest/results.json" },
    // The integration spec writes real rows through one shared database fixture.
    fileParallelism: false,
    testTimeout: 60_000,
    hookTimeout: 60_000,
  },
});
