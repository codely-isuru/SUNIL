import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "core",
    environment: "node",
    include: ["src/**/*.test.ts"],
    passWithNoTests: false,
    reporters: ["default", "json"],
    outputFile: { json: ".vitest/results.json" },
  },
});
