import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

/**
 * Stream D test-runner choice: vitest + @testing-library/react (the M1
 * decision was deferred). Rationale: vitest needs no extra transform config
 * beside the Vite React plugin, runs the same TS/JSX the app compiles, and
 * boots fast enough to keep the security-load-bearing component tests
 * (untrusted-render containment, arm-then-commit) in the inner loop.
 */
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
