import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "db",
    environment: "node",
    include: ["src/**/*.test.ts"],
    passWithNoTests: false,
    reporters: ["default", "json"],
    outputFile: { json: ".vitest/results.json" },
    // Integration specs self-skip unless SUNIL_TEST_DATABASE_URL points at a real Postgres.
    testTimeout: 30_000,
  },
});
