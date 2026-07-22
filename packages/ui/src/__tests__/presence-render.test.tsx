/**
 * `<SunilPresence />` — the accessibility contract (§8.3) and the server-render contract
 * (§9.2), plus the mount/unmount wiring the component actually uses (FR-102).
 *
 * NOTE ON METHOD. No DOM environment (`jsdom`/`happy-dom`) and no `@testing-library/react` are
 * in this repo's lockfile, and installing one mid-wave is forbidden — a `pnpm add` while two
 * other agents are working corrupts `pnpm-lock.yaml`. So the markup is asserted with React's
 * real server renderer, and the effect's cleanup is asserted through `mountPresence`, which is
 * literally the function the component's effect calls and returns. What is NOT covered here is
 * React's own effect scheduling; that is recorded as an outstanding need in the handover.
 */
import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import { SunilPresence } from "../presence/SunilPresence.js";
import { PresenceFallback } from "../presence/PresenceFallback.js";
import { mountPresence } from "../presence/mount.js";
import { PRESENCE_STATUS_SENTENCES } from "../presence/constants.js";
import { createRecordingCanvas, FakeEnv } from "./presence-fakes.js";

describe("server rendering (§9.2)", () => {
  it("renders the wrapper at its final size, so nothing shifts when the canvas appears", () => {
    const html = renderToStaticMarkup(<SunilPresence state="idle" size="md" />);
    expect(html).toContain('class="sunil-presence"');
    expect(html).toContain("width:320px");
    expect(html).toContain("height:320px");
  });

  it("accepts sm / lg / a numeric size", () => {
    expect(renderToStaticMarkup(<SunilPresence size="sm" />)).toContain("width:200px");
    expect(renderToStaticMarkup(<SunilPresence size="lg" />)).toContain("width:440px");
    expect(renderToStaticMarkup(<SunilPresence size={280} />)).toContain("width:280px");
  });

  it("does not emit a <canvas> on the server — it mounts on the client only", () => {
    const html = renderToStaticMarkup(<SunilPresence />);
    expect(html).not.toContain("<canvas");
    // The static SVG stands in until the canvas mounts, so the box is never blank.
    expect(html).toContain("<svg");
  });

  it("touches no browser global while rendering on the server", () => {
    // If the component reached for window/document/performance outside an effect, this render
    // would throw in the node environment these tests run in.
    expect(() => renderToStaticMarkup(<SunilPresence state="speaking" />)).not.toThrow();
  });
});

describe("the accessible equivalent (§8.3, NFR-016)", () => {
  it("always carries the state as text, for every state", () => {
    for (const [state, sentence] of Object.entries(PRESENCE_STATUS_SENTENCES)) {
      const html = renderToStaticMarkup(
        <SunilPresence state={state as "idle" | "thinking" | "speaking"} />,
      );
      expect(html).toContain(sentence);
      expect(html).toContain('class="sunil-sr-only"');
    }
  });

  it("hides the graphics from assistive technology and keeps them out of the tab order", () => {
    const html = renderToStaticMarkup(<SunilPresence />);
    expect(html).toContain('aria-hidden="true"');
    expect(html).not.toContain("tabindex");
    expect(html).not.toContain("role=\"img\"");
  });

  it("renders the polite live region only when `announce` is left on", () => {
    expect(renderToStaticMarkup(<SunilPresence />)).toContain('role="status"');
    // The shell owns the announcement on the dashboard, so one change is never spoken twice.
    expect(renderToStaticMarkup(<SunilPresence announce={false} />)).not.toContain(
      'role="status"',
    );
  });

  it("announces nothing on mount — the live region starts empty", () => {
    const html = renderToStaticMarkup(<SunilPresence state="thinking" />);
    expect(html).toContain(
      '<div role="status" aria-live="polite" aria-atomic="true" class="sunil-sr-only"></div>',
    );
  });

  it("accepts an overriding label", () => {
    const html = renderToStaticMarkup(<SunilPresence label="SUNIL is standing by." />);
    expect(html).toContain("SUNIL is standing by.");
    expect(html).not.toContain(PRESENCE_STATUS_SENTENCES.idle);
  });
});

describe("the static SVG fallback (§9.1)", () => {
  it("is decorative and token-coloured — no literal anywhere", () => {
    const html = renderToStaticMarkup(<PresenceFallback />);
    expect(html).toContain('aria-hidden="true"');
    expect(html).toContain("var(--sunil-presence-point)");
    expect(html).toContain("var(--sunil-presence-arc)");
    expect(html).toContain("var(--sunil-presence-marker)");
    expect(html).not.toMatch(/#[0-9a-f]{6}/i);
    expect(html).not.toContain("rgba(");
  });
});

describe("the mount/unmount wiring the component uses (FR-102)", () => {
  it("mountPresence returns a cleanup that stops the loop for good", () => {
    const env = new FakeEnv();
    const canvas = createRecordingCanvas();
    const frames: number[] = [];

    const cleanup = mountPresence({
      canvas,
      env,
      onFrame: (info) => frames.push(info.frame),
      random: () => 0.5,
    });

    env.advanceFrames(5);
    expect(frames).toHaveLength(5);

    cleanup(); // ← exactly what React invokes on unmount

    env.advanceFrames(20);
    expect(frames).toHaveLength(5);
    expect(env.pendingFrames).toBe(0);
    expect(env.subscriptions.every((s) => s.disposed)).toBe(true);
  });
});
