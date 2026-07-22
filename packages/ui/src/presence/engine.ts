/**
 * The `<SunilPresence />` animation controller — a framework-free port of
 * `prototype/sunil-command-centre.html` lines 237–339, per SUNIL_PRESENCE_SPEC.md §3–§9.
 *
 * It owns no React. The component is a thin wrapper that constructs one of these in an effect
 * and calls `dispose()` in the cleanup, which is what makes FR-102 ("no animation continues
 * after unmount, verifiable by test") provable with fake timers instead of a browser.
 *
 * Three defects in the source are fixed here, deliberately and per spec:
 *   1. §5.1 — the prototype advances `t += 0.016` PER FRAME, so it runs 2.4× too fast at
 *      144 Hz. Real elapsed time is used, clamped to 50ms so a backgrounded tab does not
 *      teleport the sphere on return.
 *   2. §6.3 — the prototype allocates 680 object literals per frame and toggles `shadowBlur`
 *      ~244 times per frame. Typed arrays, an index sort and two shadow passes replace that.
 *      These are behaviour-preserving: if any of them changes the look, it is implemented wrong.
 *   3. §7.4 — the prototype hard-codes `rgba(34,211,238,…)`. Colours resolve from
 *      `--sunil-presence-*` so a future light theme re-themes the canvas for free.
 */
import type { PresenceState } from "@sunil/core/tokens";
import {
  ALPHA_QUANTISATION_STEPS,
  ARCS,
  ARC_ALPHA_CAP,
  AXIS_TILT,
  FRONT_GLOW_THRESHOLD,
  GLOW_RADIUS_RATIO,
  GLOW_RECT_RATIO,
  GOLDEN_ANGLE,
  LEVEL_PULSE_BASE,
  LEVEL_PULSE_RANGE,
  LEVEL_SMOOTHING,
  MARKER_RADIUS,
  MARKER_SHADOW_BLUR,
  MAX_DELTA_SECONDS,
  OPTICAL_LIFT,
  OPTICAL_LIFT_RATIO,
  ORBIT_ALPHA,
  ORBIT_RX,
  ORBIT_RY,
  ORBIT_TILT,
  PERSPECTIVE_STRENGTH,
  POINT_ALPHA_BASE,
  POINT_ALPHA_RANGE,
  POINT_COUNT_HIGH,
  POINT_COUNT_LOW,
  POINT_COUNT_MEDIUM,
  POINT_SHADOW_BLUR,
  POINT_SIZE_BASE,
  POINT_SIZE_RANGE,
  REDUCED_MOTION_T,
  SECOND_MARKER_ALPHA,
  SECOND_MARKER_RADIUS,
  SECOND_MARKER_TRAIL,
  SPHERE_RADIUS_RATIO,
  STATE_PARAMS,
  TWINKLE_BASE,
  TWINKLE_RANGE,
} from "./constants.js";
import type { PresenceParams } from "./constants.js";
import { fallbackPresenceColors } from "./env.js";
import type { PresenceColors, PresenceEnv, PresenceSubscription, Rgb } from "./env.js";
import { PRESENCE_STATE_CROSSFADE_MS } from "../tokens/tokens.js";

export type PresenceQuality = "auto" | "high" | "medium" | "low";
export type PresenceQualityTier = "high" | "medium" | "low";

/** The 2D context members this component uses. Typed structurally so a test can fake it. */
export interface PresenceGradient {
  addColorStop(offset: number, color: string): void;
}

export interface PresenceContext {
  fillStyle: unknown;
  strokeStyle: unknown;
  lineWidth: number;
  shadowColor: string;
  shadowBlur: number;
  setTransform(a: number, b: number, c: number, d: number, e: number, f: number): void;
  clearRect(x: number, y: number, w: number, h: number): void;
  fillRect(x: number, y: number, w: number, h: number): void;
  createRadialGradient(
    x0: number,
    y0: number,
    r0: number,
    x1: number,
    y1: number,
    r1: number,
  ): PresenceGradient;
  save(): void;
  restore(): void;
  translate(x: number, y: number): void;
  rotate(angle: number): void;
  beginPath(): void;
  setLineDash(segments: number[]): void;
  arc(x: number, y: number, r: number, start: number, end: number): void;
  ellipse(
    x: number,
    y: number,
    rx: number,
    ry: number,
    rotation: number,
    start: number,
    end: number,
  ): void;
  stroke(): void;
  fill(): void;
}

export interface PresenceCanvas {
  width: number;
  height: number;
  getContext(contextId: "2d"): PresenceContext | null;
}

export interface PresenceFrameInfo {
  readonly frame: number;
  readonly t: number;
  readonly fps: number;
}

export interface PresenceControllerOptions {
  readonly canvas: PresenceCanvas;
  readonly env: PresenceEnv;
  readonly state?: PresenceState;
  readonly quality?: PresenceQuality;
  readonly paused?: boolean;
  readonly level?: number | undefined;
  /**
   * Resolved motion decision from the Settings → Appearance control
   * (PORTAL_SHELL_SPEC.md §9). `undefined` means "follow system", i.e. read the media query.
   */
  readonly reducedMotion?: boolean | undefined;
  readonly onFrame?: ((info: PresenceFrameInfo) => void) | undefined;
  /** Injectable RNG — `Math.random()` in a render path is untestable (§3.2). */
  readonly random?: (() => number) | undefined;
  /** Called when the canvas cannot be drawn and the static SVG fallback must take over (§9). */
  readonly onFallback?: ((active: boolean) => void) | undefined;
  /** Called once per failure. A decorative component must never take a page down (§9). */
  readonly onError?: ((error: unknown) => void) | undefined;
}

export interface PresenceController {
  setState(state: PresenceState): void;
  setPaused(paused: boolean): void;
  setLevel(level: number | undefined): void;
  setReducedMotion(reducedMotion: boolean | undefined): void;
  /** Releases every resource in the §5.2 table. Idempotent. */
  dispose(): void;
  readonly isDisposed: boolean;
  /** Test/diagnostic introspection. Never used by the component itself. */
  inspect(): PresenceDiagnostics;
}

export interface PresenceDiagnostics {
  readonly running: boolean;
  readonly t: number;
  readonly frames: number;
  readonly tier: PresenceQualityTier;
  readonly pointCount: number;
  readonly reducedMotion: boolean;
  readonly fallbackActive: boolean;
  readonly params: PresenceParams;
}

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";
const TAU = Math.PI * 2;

/** `cubic-bezier(0.2, 0, 0, 1)` — `--sunil-ease-standard`, solved by bisection (§4.1). */
function easeStandard(x: number): number {
  if (x <= 0) return 0;
  if (x >= 1) return 1;
  const cx = (u: number): number => 3 * u * (1 - u) * (1 - u) * 0.2 + 3 * u * u * (1 - u) * 0 + u * u * u;
  const cy = (u: number): number => 3 * u * (1 - u) * (1 - u) * 0 + 3 * u * u * (1 - u) * 1 + u * u * u;
  let lo = 0;
  let hi = 1;
  let u = x;
  for (let i = 0; i < 20; i += 1) {
    u = (lo + hi) / 2;
    if (cx(u) < x) lo = u;
    else hi = u;
  }
  return cy(u);
}

function lerp(a: number, b: number, k: number): number {
  return a + (b - a) * k;
}

function lerpParams(a: PresenceParams, b: PresenceParams, k: number): PresenceParams {
  return {
    rotSpeed: lerp(a.rotSpeed, b.rotSpeed, k),
    pulseAmp: lerp(a.pulseAmp, b.pulseAmp, k),
    pulseFreq: lerp(a.pulseFreq, b.pulseFreq, k),
    glowAlpha: lerp(a.glowAlpha, b.glowAlpha, k),
    twinkleFreq: lerp(a.twinkleFreq, b.twinkleFreq, k),
    arcSpeedMultiplier: lerp(a.arcSpeedMultiplier, b.arcSpeedMultiplier, k),
    arcAlphaDelta: lerp(a.arcAlphaDelta, b.arcAlphaDelta, k),
    orbitSpeed: lerp(a.orbitSpeed, b.orbitSpeed, k),
    secondMarker: lerp(a.secondMarker, b.secondMarker, k),
  };
}

/** Quality tier from the rendered CSS size (§6.2). */
export function tierForSize(size: number, requested: PresenceQuality): PresenceQualityTier {
  if (requested !== "auto") return requested;
  if (size >= 320) return "high";
  if (size >= 240) return "medium";
  return "low";
}

export function pointCountForTier(tier: PresenceQualityTier): number {
  if (tier === "high") return POINT_COUNT_HIGH;
  if (tier === "medium") return POINT_COUNT_MEDIUM;
  return POINT_COUNT_LOW;
}

/** `rgba(r,g,b,a)` strings pre-built at 64 alpha steps, so the loop allocates none (§6.3). */
function buildAlphaTable(colour: Rgb): string[] {
  const table: string[] = new Array<string>(ALPHA_QUANTISATION_STEPS + 1);
  for (let i = 0; i <= ALPHA_QUANTISATION_STEPS; i += 1) {
    const alpha = i / ALPHA_QUANTISATION_STEPS;
    table[i] = `rgba(${colour.r}, ${colour.g}, ${colour.b}, ${alpha.toFixed(4)})`;
  }
  return table;
}

function quantised(table: readonly string[], alpha: number): string {
  const clamped = alpha < 0 ? 0 : alpha > 1 ? 1 : alpha;
  const index = Math.round(clamped * ALPHA_QUANTISATION_STEPS);
  return table[index] ?? table[0] ?? "";
}

function rgbCss(colour: Rgb): string {
  return `rgb(${colour.r}, ${colour.g}, ${colour.b})`;
}

export function createPresenceController(
  options: PresenceControllerOptions,
): PresenceController {
  const { canvas, env } = options;
  const random = options.random ?? Math.random;

  let disposed = false;
  let running = false;
  let frameHandle: number | null = null;
  let lastHandle: number | null = null;

  let t = 0;
  let last = 0;
  let frames = 0;
  let fps = 0;

  let state: PresenceState = options.state ?? "idle";
  let paused = options.paused ?? false;
  let level = options.level;
  let smoothedLevel = typeof level === "number" ? level : 0;
  let reducedMotionOverride = options.reducedMotion;
  let intersecting = true;
  let contextLost = false;
  let fallbackActive = false;

  let params: PresenceParams = STATE_PARAMS[state];
  let fromParams: PresenceParams = params;
  let toParams: PresenceParams = params;
  let transitionStart = -1;

  const subscriptions: PresenceSubscription[] = [];

  let ctx: PresenceContext | null = null;
  try {
    ctx = canvas.getContext("2d");
  } catch (error) {
    ctx = null;
    options.onError?.(error);
  }

  /* ---- colours (§7.4) ---- */
  let colours: PresenceColors = fallbackPresenceColors();
  let pointAlphaTable = buildAlphaTable(colours.point);
  let arcAlphaTable = buildAlphaTable(colours.arc);
  let markerCss = rgbCss(colours.marker);
  let arcCss = rgbCss(colours.arc);

  function refreshColours(): void {
    try {
      colours = env.readColors();
    } catch (error) {
      colours = fallbackPresenceColors();
      options.onError?.(error);
    }
    pointAlphaTable = buildAlphaTable(colours.point);
    arcAlphaTable = buildAlphaTable(colours.arc);
    markerCss = rgbCss(colours.marker);
    arcCss = rgbCss(colours.arc);
    gradientKey = "";
  }

  /* ---- geometry ---- */
  let width = 0;
  let height = 0;
  let dpr = 1;
  let cx = 0;
  let cy = 0;
  let radius = 0;
  let tier: PresenceQualityTier = "high";
  let pointCount = 0;
  let downgradedOnce = false;

  let px = new Float32Array(0);
  let py = new Float32Array(0);
  let pz = new Float32Array(0);
  let ptw = new Float32Array(0);
  let sx = new Float32Array(0);
  let sy = new Float32Array(0);
  let sz = new Float32Array(0);
  let order = new Uint16Array(0);

  let gradient: PresenceGradient | null = null;
  let gradientKey = "";

  /**
   * Fibonacci sphere (§3.2). Twinkle phases are seeded once and PRESERVED BY INDEX when the
   * array is rebuilt — regenerating them makes the whole sphere flicker.
   */
  function buildPoints(count: number): void {
    const previousTw = ptw;
    px = new Float32Array(count);
    py = new Float32Array(count);
    pz = new Float32Array(count);
    ptw = new Float32Array(count);
    sx = new Float32Array(count);
    sy = new Float32Array(count);
    sz = new Float32Array(count);
    order = new Uint16Array(count);

    for (let i = 0; i < count; i += 1) {
      const y = 1 - (i / (count - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const th = GOLDEN_ANGLE * i;
      px[i] = Math.cos(th) * r;
      py[i] = y;
      pz[i] = Math.sin(th) * r;
      ptw[i] = i < previousTw.length ? (previousTw[i] ?? 0) : random() * TAU;
      order[i] = i;
    }
    pointCount = count;
  }

  /** §7.2 resize path, in order. Debounced to one execution per animation frame by the caller. */
  function resize(): boolean {
    const box = env.measure();
    const nextDpr = Math.min(env.devicePixelRatio() || 1, 2);
    if (box.width === width && box.height === height && nextDpr === dpr) return false;

    width = box.width;
    height = box.height;
    dpr = nextDpr;
    if (width <= 0 || height <= 0) return true;

    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    // Assigning width/height resets the context — the transform must be re-applied (§3.1).
    ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);

    cx = width / 2;
    cy = height / 2 - Math.min(OPTICAL_LIFT, height * OPTICAL_LIFT_RATIO);
    radius = Math.min(width, height) * SPHERE_RADIUS_RATIO;

    const nextTier = downgradedOnce ? "low" : tierForSize(Math.min(width, height), options.quality ?? "auto");
    if (nextTier !== tier || pointCount === 0) {
      tier = nextTier;
      buildPoints(pointCountForTier(tier));
    }
    gradientKey = "";
    return true;
  }

  function currentParams(nowMs: number): PresenceParams {
    if (transitionStart < 0) return toParams;
    const elapsed = nowMs - transitionStart;
    if (elapsed >= PRESENCE_STATE_CROSSFADE_MS) {
      transitionStart = -1;
      return toParams;
    }
    return lerpParams(fromParams, toParams, easeStandard(elapsed / PRESENCE_STATE_CROSSFADE_MS));
  }

  function pulseAmplitude(active: PresenceParams): number {
    if (state !== "speaking" || typeof level !== "number") return active.pulseAmp;
    const clamped = level < 0 ? 0 : level > 1 ? 1 : level;
    const target = LEVEL_PULSE_BASE + LEVEL_PULSE_RANGE * clamped;
    smoothedLevel += (target - smoothedLevel) * LEVEL_SMOOTHING;
    return smoothedLevel;
  }

  function drawGlow(active: PresenceParams): void {
    if (!ctx) return;
    const key = `${radius.toFixed(2)}:${active.glowAlpha.toFixed(3)}:${colours.glow.r},${colours.glow.g},${colours.glow.b}`;
    if (gradient === null || key !== gradientKey) {
      const g = ctx.createRadialGradient(cx, cy, 0, cx, cy, radius * GLOW_RADIUS_RATIO);
      const { r, g: gg, b } = colours.glow;
      g.addColorStop(0, `rgba(${r}, ${gg}, ${b}, ${active.glowAlpha.toFixed(4)})`);
      g.addColorStop(1, `rgba(${r}, ${gg}, ${b}, 0)`);
      gradient = g;
      gradientKey = key;
    }
    ctx.fillStyle = gradient;
    const extent = radius * GLOW_RECT_RATIO;
    ctx.fillRect(cx - extent, cy - extent, extent * 2, extent * 2);
  }

  function drawArcs(time: number, active: PresenceParams): void {
    if (!ctx) return;
    const arcCount = tier === "low" ? 2 : ARCS.length;
    for (let i = 0; i < arcCount; i += 1) {
      const arc = ARCS[i];
      if (!arc) continue;
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(time * arc.speed * active.arcSpeedMultiplier);
      ctx.beginPath();
      ctx.setLineDash([arc.dash[0], arc.dash[1]]);
      ctx.arc(0, 0, radius * arc.radius, 0, TAU);
      ctx.strokeStyle = quantised(
        arcAlphaTable,
        Math.min(arc.alpha + active.arcAlphaDelta, ARC_ALPHA_CAP),
      );
      ctx.lineWidth = arc.width;
      ctx.stroke();
      ctx.restore();
    }
    ctx.setLineDash([]);
  }

  function drawPoints(time: number, active: PresenceParams): void {
    if (!ctx) return;
    const rot = time * active.rotSpeed;
    const cosR = Math.cos(rot);
    const sinR = Math.sin(rot);
    const cosT = Math.cos(AXIS_TILT);
    const sinT = Math.sin(AXIS_TILT);
    const pulse = 1 + pulseAmplitude(active) * Math.sin(time * active.pulseFreq);

    for (let i = 0; i < pointCount; i += 1) {
      const x = px[i] ?? 0;
      const y = py[i] ?? 0;
      const z = pz[i] ?? 0;
      const x1 = x * cosR + z * sinR;
      const z1 = -x * sinR + z * cosR;
      const y2 = y * cosT - z1 * sinT;
      const z2 = y * sinT + z1 * cosT;
      const persp = 1 / (1 - z2 * PERSPECTIVE_STRENGTH);
      sx[i] = cx + x1 * radius * pulse * persp;
      sy[i] = cy + y2 * radius * pulse * persp;
      sz[i] = z2;
    }

    // Painter's algorithm over the INDEX array. `z` changes smoothly, so the array is almost
    // sorted every frame and this insertion sort is near-O(n) (§6.3).
    for (let i = 1; i < pointCount; i += 1) {
      const idx = order[i] ?? 0;
      const key = sz[idx] ?? 0;
      let j = i - 1;
      while (j >= 0 && (sz[order[j] ?? 0] ?? 0) > key) {
        order[j + 1] = order[j] ?? 0;
        j -= 1;
      }
      order[j + 1] = idx;
    }

    const glowOn = tier !== "low";
    // Two passes so `shadowBlur` is set twice per frame instead of ~244 times (§6.3).
    for (let pass = 0; pass < 2; pass += 1) {
      if (pass === 1) {
        if (!glowOn) break;
        ctx.shadowColor = arcCss;
        ctx.shadowBlur = POINT_SHADOW_BLUR;
      }
      for (let i = 0; i < pointCount; i += 1) {
        const idx = order[i] ?? 0;
        const front = ((sz[idx] ?? 0) + 1) / 2;
        const isGlowing = glowOn && front > FRONT_GLOW_THRESHOLD;
        if (pass === 0 ? isGlowing : !isGlowing) continue;
        const twinkle =
          TWINKLE_BASE +
          TWINKLE_RANGE * Math.sin(time * active.twinkleFreq + (ptw[idx] ?? 0));
        const alpha = (POINT_ALPHA_BASE + front * POINT_ALPHA_RANGE) * twinkle;
        ctx.beginPath();
        ctx.fillStyle = quantised(pointAlphaTable, alpha);
        ctx.arc(sx[idx] ?? 0, sy[idx] ?? 0, POINT_SIZE_BASE + front * POINT_SIZE_RANGE, 0, TAU);
        ctx.fill();
      }
    }
    ctx.shadowBlur = 0;
  }

  function drawOrbit(time: number, active: PresenceParams): void {
    if (!ctx) return;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(ORBIT_TILT);
    ctx.beginPath();
    ctx.ellipse(0, 0, radius * ORBIT_RX, radius * ORBIT_RY, 0, 0, TAU);
    ctx.strokeStyle = quantised(arcAlphaTable, ORBIT_ALPHA);
    ctx.lineWidth = 1;
    ctx.stroke();

    const angle = time * active.orbitSpeed;
    ctx.beginPath();
    ctx.fillStyle = markerCss;
    ctx.shadowColor = arcCss;
    ctx.shadowBlur = MARKER_SHADOW_BLUR;
    ctx.arc(Math.cos(angle) * radius * ORBIT_RX, Math.sin(angle) * radius * ORBIT_RY, MARKER_RADIUS, 0, TAU);
    ctx.fill();

    // `thinking` only: a trailing second marker implying work in flight (§4).
    if (active.secondMarker > 0.01) {
      const trailing = angle - SECOND_MARKER_TRAIL;
      ctx.beginPath();
      ctx.fillStyle = quantised(arcAlphaTable, SECOND_MARKER_ALPHA * active.secondMarker);
      ctx.arc(
        Math.cos(trailing) * radius * ORBIT_RX,
        Math.sin(trailing) * radius * ORBIT_RY,
        SECOND_MARKER_RADIUS,
        0,
        TAU,
      );
      ctx.fill();
    }
    ctx.shadowBlur = 0;
    ctx.restore();
  }

  /** Draw order is load-bearing: glow → arcs → points → orbital ring (§3.3). */
  function render(time: number, nowMs: number): void {
    if (!ctx || width <= 0 || height <= 0) return;
    const active = currentParams(nowMs);
    params = active;
    ctx.clearRect(0, 0, width, height);
    drawGlow(active);
    drawArcs(time, active);
    drawPoints(time, active);
    drawOrbit(time, active);
  }

  function isReducedMotion(): boolean {
    if (typeof reducedMotionOverride === "boolean") return reducedMotionOverride;
    return motionQuery?.matches ?? false;
  }

  /** §5.4 — each condition is checked BEFORE scheduling the next frame, never inside it. */
  function shouldRun(): boolean {
    if (disposed || ctx === null || contextLost) return false;
    if (paused) return false;
    if (env.isDocumentHidden()) return false;
    if (!intersecting) return false;
    if (isReducedMotion()) return false;
    return width > 0 && height > 0;
  }

  function schedule(): void {
    if (disposed || !shouldRun()) {
      running = false;
      return;
    }
    running = true;
    frameHandle = env.requestAnimationFrame(onAnimationFrame);
    lastHandle = frameHandle;
  }

  function onAnimationFrame(): void {
    // THE GUARD THAT MATTERS (§5.2). A callback already scheduled still runs once after
    // cancellation in some engines; without this it re-queues and the loop never dies.
    if (disposed) return;
    try {
      const nowMs = env.now();
      const dt = Math.min((nowMs - last) / 1000, MAX_DELTA_SECONDS);
      last = nowMs;
      t += dt;
      frames += 1;
      fps = dt > 0 ? 1 / dt : 0;
      if (resizePending) {
        resizePending = false;
        resize();
      }
      maybeDowngrade(dt);
      render(t, nowMs);
      options.onFrame?.({ frame: frames, t, fps });
    } catch (error) {
      // A decorative component must never take a page down — and the pages it sits on are the
      // sign-in page and the dashboard (§9).
      failToFallback(error);
      return;
    }
    schedule();
  }

  let slowFrames = 0;
  function maybeDowngrade(dt: number): void {
    if (downgradedOnce || tier === "low" || dt <= 0) return;
    if (1 / dt < 45) slowFrames += 1;
    else slowFrames = 0;
    if (slowFrames >= 60) {
      // One-way within a mount: an oscillating quality tier is worse than a low frame rate.
      downgradedOnce = true;
      tier = "low";
      buildPoints(pointCountForTier(tier));
      slowFrames = 0;
    }
  }

  function failToFallback(error: unknown): void {
    cancel();
    fallbackActive = true;
    options.onFallback?.(true);
    options.onError?.(error);
  }

  function cancel(): void {
    if (frameHandle !== null) {
      env.cancelAnimationFrame(frameHandle);
      frameHandle = null;
    }
    running = false;
  }

  /** Under reduced motion exactly one frame is drawn, at a fixed `t = 1.9` (§8.1). */
  function renderStaticFrame(): void {
    if (!ctx) return;
    try {
      render(REDUCED_MOTION_T, env.now());
      frames += 1;
      options.onFrame?.({ frame: frames, t: REDUCED_MOTION_T, fps: 0 });
    } catch (error) {
      failToFallback(error);
    }
  }

  /** Recomputes whether the loop should be running, and starts or stops it accordingly. */
  function sync(): void {
    if (disposed) return;
    if (isReducedMotion()) {
      cancel();
      renderStaticFrame();
      return;
    }
    if (shouldRun()) {
      if (!running) {
        // On resume, reset `last` BEFORE the first frame so `dt` is not the length of the
        // pause (§5.4).
        last = env.now();
        schedule();
      }
      return;
    }
    cancel();
  }

  let resizePending = false;

  /* ---- subscriptions (§5.2) ---- */
  const motionQuery = env.matchMedia(REDUCED_MOTION_QUERY);
  if (motionQuery) {
    subscriptions.push(
      motionQuery.subscribe(() => {
        sync();
      }),
    );
  }
  subscriptions.push(
    env.observeResize(() => {
      // Debounced to one execution per animation frame; ResizeObserver fires many times
      // during a drag (§7.2).
      if (running) {
        resizePending = true;
        return;
      }
      if (resize()) sync();
      if (!running && isReducedMotion()) renderStaticFrame();
    }),
  );
  subscriptions.push(
    env.observeIntersection((visible) => {
      intersecting = visible;
      sync();
    }),
  );
  subscriptions.push(
    env.onVisibilityChange(() => {
      sync();
    }),
  );
  subscriptions.push(
    env.observeTheme(() => {
      refreshColours();
      if (!running) renderStaticFrame();
    }),
  );
  subscriptions.push(
    env.observeContextLoss((lost) => {
      contextLost = lost;
      if (lost) {
        cancel();
        fallbackActive = true;
        options.onFallback?.(true);
        return;
      }
      fallbackActive = false;
      options.onFallback?.(false);
      width = 0;
      height = 0;
      resize();
      sync();
    }),
  );

  /* ---- start ---- */
  refreshColours();
  resize();
  if (ctx === null) {
    fallbackActive = true;
    options.onFallback?.(true);
  } else {
    last = env.now();
    sync();
  }

  return {
    setState(next) {
      if (next === state) return;
      state = next;
      // `t` is NEVER reset on a state change — resetting teleports the rotation and every
      // twinkle phase, which is instantly visible (§4.1).
      fromParams = params;
      toParams = STATE_PARAMS[next];
      transitionStart = env.now();
      if (!running) renderStaticFrame();
    },
    setPaused(next) {
      if (next === paused) return;
      paused = next;
      sync();
    },
    setLevel(next) {
      level = next;
      if (typeof next !== "number") smoothedLevel = 0;
    },
    setReducedMotion(next) {
      if (next === reducedMotionOverride) return;
      reducedMotionOverride = next;
      sync();
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      cancel();
      for (const subscription of subscriptions) subscription.dispose();
      subscriptions.length = 0;
    },
    get isDisposed() {
      return disposed;
    },
    inspect() {
      return {
        running,
        t,
        frames,
        tier,
        pointCount,
        reducedMotion: isReducedMotion(),
        fallbackActive,
        params,
        lastFrameHandle: lastHandle,
      } as PresenceDiagnostics & { lastFrameHandle: number | null };
    },
  };
}
