import { defineConfig } from "vitest/config";

export default defineConfig({
  // The app's tsconfig sets `jsx: "preserve"` because Next owns JSX compilation. Vitest's
  // esbuild pass would then emit raw JSX into a file node cannot execute, so the automatic
  // runtime is selected explicitly here. This affects tests only.
  esbuild: { jsx: "automatic" },
  test: {
    name: "web",
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    passWithNoTests: true,
    reporters: ["default", "json"],
    outputFile: { json: ".vitest/results.json" },
  },
});
