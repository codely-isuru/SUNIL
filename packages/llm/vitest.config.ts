import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    name: "llm",
    environment: "node",
    include: ["src/**/*.test.ts"],
    passWithNoTests: true,
    reporters: ["default", "json"],
    outputFile: { json: ".vitest/results.json" },
  },
});
