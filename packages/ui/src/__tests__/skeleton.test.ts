import { describe, expect, it } from "vitest";
import { cssVar, cssVarName } from "@sunil/core/tokens";
import { PACKAGE_NAME, PRESENCE_STATES } from "../index.js";

describe("@sunil/ui skeleton", () => {
  it("is wired into the workspace", () => {
    expect(PACKAGE_NAME).toBe("@sunil/ui");
  });

  it("exposes the presence vocabulary for <SunilPresence /> (FR-102)", () => {
    expect(PRESENCE_STATES).toEqual(["idle", "thinking", "speaking"]);
  });

  it("namespaces every design token", () => {
    expect(cssVarName("color", "bg")).toBe("--sunil-color-bg");
    expect(cssVar("space", "md")).toBe("var(--sunil-space-md)");
  });
});
