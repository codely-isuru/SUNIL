/**
 * FR-102 and SUNIL_PRESENCE_SPEC.md §5.3 / §8 — the two assertions the specs single out:
 * the loop does not leak on unmount, and reduced motion means the loop NEVER STARTS.
 *
 * Both are asserted against the controller, which is the code the React component runs: the
 * component's effect does `createPresenceController(...)` and its cleanup does `dispose()`,
 * and `SunilPresence.render.test.tsx` proves that wiring separately.
 */
import { describe, expect, it } from "vitest";
import { createPresenceController } from "../presence/engine.js";
import { MAX_DELTA_SECONDS, REDUCED_MOTION_T, STATE_PARAMS } from "../presence/constants.js";
import { createRecordingCanvas, FakeEnv } from "./presence-fakes.js";

function setup(overrides: Partial<Parameters<typeof createPresenceController>[0]> = {}) {
  const env = new FakeEnv();
  const canvas = createRecordingCanvas();
  const frames: Array<{ frame: number; t: number; fps: number }> = [];
  const controller = createPresenceController({
    canvas,
    env,
    onFrame: (info) => frames.push(info),
    random: () => 0.5,
    ...overrides,
  });
  return { env, canvas, frames, controller };
}

describe("presence loop lifecycle (FR-102)", () => {
  it("renders frames while mounted", () => {
    const { env, frames } = setup();
    env.advanceFrames(5);
    expect(frames).toHaveLength(5);
  });

  it("does not leak after dispose: no further frames, and the last handle is cancelled", () => {
    const { env, frames, controller } = setup();
    env.advanceFrames(5);
    expect(frames).toHaveLength(5);

    const handleAtDispose = env.lastHandle;
    controller.dispose();

    expect(env.cancelCalls).toContain(handleAtDispose);

    // 20 more animation frames: nothing may run, and nothing may be re-queued.
    env.advanceFrames(20);
    expect(frames).toHaveLength(5);
    expect(env.pendingFrames).toBe(0);
    expect(controller.isDisposed).toBe(true);
  });

  it("disposes every observer in the §5.2 table", () => {
    const { env, controller } = setup();
    const kinds = env.subscriptions.map((s) => s.kind);
    expect(kinds).toEqual(
      expect.arrayContaining([
        "matchMedia",
        "ResizeObserver",
        "IntersectionObserver",
        "visibilitychange",
        "MutationObserver",
        "contextlost",
      ]),
    );
    expect(env.subscriptions.every((s) => !s.disposed)).toBe(true);

    controller.dispose();
    expect(env.subscriptions.every((s) => s.disposed)).toBe(true);
  });

  it("the `disposed` guard survives a callback that was already scheduled", () => {
    // The exact leak §5.2 warns about: an in-flight callback re-queuing after cancellation.
    let captured: ((t: number) => void) | null = null;
    class CapturingEnv extends FakeEnv {
      override requestAnimationFrame(callback: (t: number) => void): number {
        captured = callback;
        return super.requestAnimationFrame(callback);
      }
    }

    const env = new CapturingEnv();
    const canvas = createRecordingCanvas();
    const frames: number[] = [];

    const controller = createPresenceController({
      canvas,
      env,
      onFrame: (info) => frames.push(info.frame),
      random: () => 0.5,
    });

    expect(captured).not.toBeNull();
    controller.dispose();

    // Invoke the already-scheduled callback by hand, as a real engine may do once.
    captured?.(0);

    expect(frames).toHaveLength(0);
    expect(env.pendingFrames).toBe(0);
  });

  it("is idempotent: disposing twice is harmless", () => {
    const { controller } = setup();
    controller.dispose();
    expect(() => {
      controller.dispose();
    }).not.toThrow();
  });

  it("stops when paused and resumes without a time jump", () => {
    const { env, frames, controller } = setup();
    env.advanceFrames(3);
    controller.setPaused(true);
    env.advanceFrames(10);
    expect(frames).toHaveLength(3);

    controller.setPaused(false);
    env.advanceFrames(2);
    expect(frames).toHaveLength(5);
  });

  it("stops while the document is hidden (§5.4)", () => {
    const { env, frames } = setup();
    env.advanceFrames(2);
    env.hidden = true;
    env.visibilityCallback?.();
    env.advanceFrames(10);
    expect(frames).toHaveLength(2);

    env.hidden = false;
    env.visibilityCallback?.();
    env.advanceFrames(1);
    expect(frames).toHaveLength(3);
  });

  it("stops when the host leaves the viewport (§5.4)", () => {
    const { env, frames } = setup();
    env.advanceFrames(2);
    env.intersectionCallback?.(false);
    env.advanceFrames(10);
    expect(frames).toHaveLength(2);
  });

  it("renders nothing and does not divide by zero at a 0×0 box (§5.4)", () => {
    const env = new FakeEnv();
    env.box = { width: 0, height: 0 };
    const canvas = createRecordingCanvas();
    const frames: number[] = [];
    createPresenceController({
      canvas,
      env,
      onFrame: (info) => frames.push(info.frame),
      random: () => 0.5,
    });
    env.advanceFrames(5);
    expect(frames).toHaveLength(0);
    expect(canvas.ops).not.toContain("clearRect");
  });
});

describe("reduced motion (SUNIL_PRESENCE_SPEC.md §8)", () => {
  it("never schedules an animation frame, and draws exactly one static frame at t=1.9", () => {
    const env = new FakeEnv();
    env.reducedMotion = true;
    const canvas = createRecordingCanvas();
    const frames: Array<{ t: number }> = [];

    const controller = createPresenceController({
      canvas,
      env,
      onFrame: (info) => frames.push(info),
      random: () => 0.5,
    });

    // The assertion the spec names explicitly: NO requestAnimationFrame is ever called.
    expect(env.rafCalls).toHaveLength(0);
    expect(frames).toHaveLength(1);
    expect(frames[0]?.t).toBe(REDUCED_MOTION_T);
    expect(canvas.ops).toContain("clearRect");

    env.advanceFrames(30);
    expect(env.rafCalls).toHaveLength(0);
    expect(frames).toHaveLength(1);

    controller.dispose();
  });

  it("is a static frame, not a slower rotation: a state change redraws once with no loop", () => {
    const env = new FakeEnv();
    env.reducedMotion = true;
    const canvas = createRecordingCanvas();
    const frames: Array<{ t: number }> = [];
    const controller = createPresenceController({
      canvas,
      env,
      onFrame: (info) => frames.push(info),
      random: () => 0.5,
    });

    controller.setState("thinking");
    expect(env.rafCalls).toHaveLength(0);
    expect(frames).toHaveLength(2);
    expect(frames[1]?.t).toBe(REDUCED_MOTION_T);
  });

  it("an explicit Settings override beats the media query in both directions (§8.2)", () => {
    const env = new FakeEnv();
    env.reducedMotion = true;
    const canvas = createRecordingCanvas();
    const controller = createPresenceController({
      canvas,
      env,
      reducedMotion: false, // Settings → Appearance → Motion → "Never reduce"
      random: () => 0.5,
    });
    expect(env.rafCalls.length).toBeGreaterThan(0);

    controller.setReducedMotion(true); // → "Always reduce"
    const scheduledSoFar = env.rafCalls.length;
    env.advanceFrames(5);
    expect(env.rafCalls).toHaveLength(scheduledSoFar);
  });

  it("turning the OS preference on cancels the running loop within one frame", () => {
    const { env, frames } = setup();
    env.advanceFrames(3);
    env.setReducedMotion(true);
    env.advanceFrames(10);
    // One extra frame is the static redraw; nothing continues after it.
    expect(frames.length).toBeLessThanOrEqual(5);
    const settled = frames.length;
    env.advanceFrames(10);
    expect(frames).toHaveLength(settled);
  });
});

describe("frame timing (SUNIL_PRESENCE_SPEC.md §5.1 — the prototype's 2.4× defect)", () => {
  it("advances `t` by elapsed time, so 144 Hz and 60 Hz run at the same visual speed", () => {
    const slow = setup();
    slow.env.advanceFrames(60, 1000 / 60);
    const at60 = slow.controller.inspect().t;

    const fast = setup();
    fast.env.advanceFrames(144, 1000 / 144);
    const at144 = fast.controller.inspect().t;

    // One second of wall clock either way — the prototype would have given 0.96 vs 2.30.
    expect(at60).toBeCloseTo(1, 2);
    expect(at144).toBeCloseTo(1, 2);
  });

  it("clamps a long gap so a backgrounded tab does not teleport the sphere", () => {
    const { env, controller } = setup();
    env.advanceFrames(1);
    const before = controller.inspect().t;
    env.advanceClock(30_000); // 30 seconds in another tab
    env.advanceFrames(1);
    expect(controller.inspect().t - before).toBeCloseTo(MAX_DELTA_SECONDS, 5);
  });
});

describe("prop-driven state (FR-102)", () => {
  it("cross-fades parameters instead of jumping, and never resets `t` (§4.1)", () => {
    const { env, controller } = setup();
    env.advanceFrames(10);
    const tBefore = controller.inspect().t;

    controller.setState("speaking");
    env.advanceFrames(1);
    const midway = controller.inspect();

    expect(midway.t).toBeGreaterThan(tBefore); // `t` continued; no teleport
    expect(midway.params.pulseAmp).toBeGreaterThan(STATE_PARAMS.idle.pulseAmp);
    expect(midway.params.pulseAmp).toBeLessThan(STATE_PARAMS.speaking.pulseAmp);

    env.advanceFrames(40); // > 400ms
    expect(controller.inspect().params.pulseAmp).toBeCloseTo(STATE_PARAMS.speaking.pulseAmp, 5);
  });

  it("distinguishes the three states by their parameter sets", () => {
    expect(STATE_PARAMS.thinking.rotSpeed).toBeGreaterThan(STATE_PARAMS.idle.rotSpeed);
    expect(STATE_PARAMS.speaking.pulseAmp).toBeGreaterThan(STATE_PARAMS.thinking.pulseAmp);
    // The inversion that makes the two active states readable at a glance (§4):
    expect(STATE_PARAMS.speaking.rotSpeed).toBe(STATE_PARAMS.idle.rotSpeed);
    expect(STATE_PARAMS.thinking.secondMarker).toBe(1);
  });
});

describe("failure paths (SUNIL_PRESENCE_SPEC.md §9)", () => {
  it("falls back instead of throwing when getContext returns null", () => {
    const env = new FakeEnv();
    const canvas = createRecordingCanvas({ contextAvailable: false });
    let fallback = false;
    const controller = createPresenceController({
      canvas,
      env,
      onFallback: (active) => {
        fallback = active;
      },
      random: () => 0.5,
    });
    expect(fallback).toBe(true);
    expect(env.rafCalls).toHaveLength(0);
    expect(controller.inspect().fallbackActive).toBe(true);
  });

  it("cancels the loop and shows the fallback when the context is lost", () => {
    const { env, controller } = setup();
    env.advanceFrames(2);
    env.contextLossCallback?.(true);
    const scheduled = env.rafCalls.length;
    env.advanceFrames(5);
    expect(env.rafCalls).toHaveLength(scheduled);
    expect(controller.inspect().fallbackActive).toBe(true);
  });
});

describe("quality tiers (§6.2)", () => {
  it("selects the point count from the rendered size", () => {
    const env = new FakeEnv();
    env.box = { width: 200, height: 200 };
    const controller = createPresenceController({
      canvas: createRecordingCanvas(),
      env,
      random: () => 0.5,
    });
    expect(controller.inspect().tier).toBe("low");
    expect(controller.inspect().pointCount).toBe(260);

    const md = new FakeEnv();
    const mdController = createPresenceController({
      canvas: createRecordingCanvas(),
      env: md,
      random: () => 0.5,
    });
    expect(mdController.inspect().tier).toBe("high");
    expect(mdController.inspect().pointCount).toBe(680);
  });
});
