import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "agents",
    environment: "node",
    include: ["src/**/*.test.ts"],
    passWithNoTests: true,
    reporters: ["default", "json"],
    outputFile: { json: ".vitest/results.json" },
  },
});
