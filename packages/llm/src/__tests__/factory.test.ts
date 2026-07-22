/**
 * FR-065 — "a mock transport ... cannot be selected by a production configuration profile".
 *
 * Following T1's discipline: prove the fence, don't trust it.
 */
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { InvariantViolationError, ValidationError } from "@sunil/core";
import { createProvider, createProviderWithTransport } from "../factory.js";
import { MockTransport } from "../testing/mock-transport.js";
import { FakeSecretStore, SENTINEL_KEY, makeRecorder } from "./support.js";

const deps = () => ({
  secrets: new FakeSecretStore({ "llm:anthropic:api-key": SENTINEL_KEY }),
  usage: makeRecorder().recorder,
});

const originalNodeEnv = process.env["NODE_ENV"];

afterEach(() => {
  if (originalNodeEnv === undefined) delete process.env["NODE_ENV"];
  else process.env["NODE_ENV"] = originalNodeEnv;
});

describe("the production factory cannot select a mocked transport", () => {
  it("takes no transport parameter at all", () => {
    // (config, deps) — there is no third parameter to pass a mock through.
    expect(createProvider).toHaveLength(2);
  });

  it("builds all three providers with usage recording applied", () => {
    const anthropic = createProvider(
      { slug: "anthropic", credentialName: "llm:anthropic:api-key" },
      deps(),
    );
    const openai = createProvider({ slug: "openai", credentialName: "llm:openai:api-key" }, deps());
    const ollama = createProvider({ slug: "ollama", baseUrl: "http://localhost:11434" }, deps());

    for (const provider of [anthropic, openai, ollama]) {
      expect(provider.verification).toBe("mock-verified");
      expect(typeof provider.complete).toBe("function");
    }
    expect(anthropic.slug).toBe("anthropic");
    expect(openai.slug).toBe("openai");
    expect(ollama.slug).toBe("ollama");
  });

  it("requires a SecretStore reference for the credentialled providers", () => {
    expect(() => createProvider({ slug: "openai" }, deps())).toThrow(ValidationError);
    expect(() => createProvider({ slug: "ollama" }, deps())).not.toThrow();
  });

  it("refuses an injected transport outside NODE_ENV=test", () => {
    const transport = new MockTransport([]).fetch;

    for (const env of ["production", "development", undefined]) {
      if (env === undefined) delete process.env["NODE_ENV"];
      else process.env["NODE_ENV"] = env;

      expect(() =>
        createProviderWithTransport(
          { slug: "anthropic", credentialName: "llm:anthropic:api-key" },
          deps(),
          transport,
        ),
      ).toThrow(InvariantViolationError);
    }
  });

  it("permits an injected transport under NODE_ENV=test — which is how this suite runs", () => {
    process.env["NODE_ENV"] = "test";
    expect(() =>
      createProviderWithTransport(
        { slug: "anthropic", credentialName: "llm:anthropic:api-key" },
        deps(),
        new MockTransport([]).fetch,
      ),
    ).not.toThrow();
  });
});

describe("the mock lives behind a structural fence, not a convention", () => {
  // Vitest runs with the package directory as cwd (both under pnpm --filter and turbo).
  const packageRoot = process.cwd();
  const srcRoot = join(packageRoot, "src");

  function collectSources(dir: string, found: string[] = []): string[] {
    for (const entry of readdirSync(dir)) {
      const full = join(dir, entry);
      if (statSync(full).isDirectory()) {
        if (entry === "__tests__" || entry === "testing") continue;
        collectSources(full, found);
      } else if (entry.endsWith(".ts")) {
        found.push(full);
      }
    }
    return found;
  }

  it("is scanning the package it thinks it is", () => {
    expect(existsSync(join(srcRoot, "factory.ts"))).toBe(true);
  });

  it("has no production source file importing from ./testing", () => {
    const offenders = collectSources(srcRoot).filter((file) =>
      /from\s+["'][^"']*\/testing\//.test(readFileSync(file, "utf8")),
    );
    expect(offenders).toEqual([]);
  });

  it("does not re-export the mock transport from the package barrel", () => {
    // Comments may DISCUSS the fence; only executable statements matter.
    const barrel = readFileSync(join(srcRoot, "index.ts"), "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(barrel).not.toMatch(/MockTransport/);
    expect(barrel).not.toMatch(/from\s+["']\.\/testing/);
  });

  it("exposes only the '.' entry point, so ./testing is unreachable from other workspaces", () => {
    const manifest = JSON.parse(readFileSync(join(packageRoot, "package.json"), "utf8")) as {
      name: string;
      exports: Record<string, unknown>;
    };
    expect(manifest.name).toBe("@sunil/llm");
    expect(Object.keys(manifest.exports)).toEqual(["."]);
  });
});
