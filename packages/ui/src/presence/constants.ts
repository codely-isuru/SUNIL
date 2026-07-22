/**
 * `<SunilPresence />` constants — SUNIL_PRESENCE_SPEC.md §3.4 and §4.
 *
 * Every value here is transcribed verbatim from `prototype/sunil-command-centre.html`
 * (read-only, A-15) EXCEPT the `thinking` column of `STATE_PARAMS`, which §4 introduces
 * because FR-102 requires a third state and the prototype has no reference for it.
 *
 * The names are new; the numbers are not. A reviewer can diff this file against §3.4.
 */
import type { PresenceState } from "@sunil/core/tokens";

/* ---- Geometry (§3.1, §3.2) ---- */

export const POINT_COUNT_HIGH = 680;
export const POINT_COUNT_MEDIUM = 420;
export const POINT_COUNT_LOW = 260;

export const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
export const SPHERE_RADIUS_RATIO = 0.21;
/** `CY = H/2 - 14` in the prototype; generalised to `min(14, H*0.045)` so it holds at 200px. */
export const OPTICAL_LIFT = 14;
export const OPTICAL_LIFT_RATIO = 0.045;
export const AXIS_TILT = 0.42;
export const PERSPECTIVE_STRENGTH = 0.28;

/* ---- Points (§3.3) ---- */

export const POINT_ALPHA_BASE = 0.1;
export const POINT_ALPHA_RANGE = 0.75;
export const POINT_SIZE_BASE = 0.7;
export const POINT_SIZE_RANGE = 1.5;
export const TWINKLE_BASE = 0.75;
export const TWINKLE_RANGE = 0.25;
export const FRONT_GLOW_THRESHOLD = 0.82;
export const POINT_SHADOW_BLUR = 7;

/* ---- Core glow (§3.3) ---- */

export const GLOW_RADIUS_RATIO = 2.1;
export const GLOW_RECT_RATIO = 2.2;

/* ---- Orbital ring (§3.3) ---- */

export const ORBIT_RX = 1.34;
export const ORBIT_RY = 0.44;
export const ORBIT_TILT = -0.3;
export const ORBIT_ALPHA = 0.4;
export const MARKER_RADIUS = 3.4;
export const MARKER_SHADOW_BLUR = 14;
/** `thinking` only: a second marker trailing the first (§4). */
export const SECOND_MARKER_TRAIL = 0.6;
export const SECOND_MARKER_ALPHA = 0.6;
export const SECOND_MARKER_RADIUS = 2.2;

/* ---- HUD arcs (§3.3). The middle arc COUNTER-ROTATES; do not "tidy" the sign. ---- */

export interface ArcSpec {
  readonly radius: number;
  readonly width: number;
  readonly dash: readonly [number, number];
  readonly speed: number;
  readonly alpha: number;
}

export const ARCS: readonly ArcSpec[] = [
  { radius: 1.55, width: 1.4, dash: [3, 9], speed: 0.22, alpha: 0.5 },
  { radius: 1.78, width: 1.0, dash: [16, 10], speed: -0.13, alpha: 0.35 },
  { radius: 2.02, width: 0.8, dash: [2, 5], speed: 0.07, alpha: 0.25 },
];

export const ARC_ALPHA_CAP = 0.6;

/* ---- Loop (§5.1) ---- */

/** A backgrounded tab must not teleport the sphere on return: clamp `dt` to 3 frames @60fps. */
export const MAX_DELTA_SECONDS = 0.05;
/** The single frame drawn under `prefers-reduced-motion` (§8.1). Use exactly this value. */
export const REDUCED_MOTION_T = 1.9;
/** One-pole smoothing coefficient for the `level` prop (§4.2). */
export const LEVEL_SMOOTHING = 0.15;
/** Alpha strings are quantised to this many steps and looked up (§6.3). */
export const ALPHA_QUANTISATION_STEPS = 64;

/* ---- Per-state parameters (§4) ---- */

export interface PresenceParams {
  readonly rotSpeed: number;
  readonly pulseAmp: number;
  readonly pulseFreq: number;
  readonly glowAlpha: number;
  readonly twinkleFreq: number;
  readonly arcSpeedMultiplier: number;
  readonly arcAlphaDelta: number;
  readonly orbitSpeed: number;
  /** `thinking` draws a second orbital marker; 0 or 1 so it can be interpolated. */
  readonly secondMarker: number;
}

export const STATE_PARAMS: Readonly<Record<PresenceState, PresenceParams>> = {
  idle: {
    rotSpeed: 0.28,
    pulseAmp: 0.015,
    pulseFreq: 1.4,
    glowAlpha: 0.12,
    twinkleFreq: 2.0,
    arcSpeedMultiplier: 1.0,
    arcAlphaDelta: 0,
    orbitSpeed: 0.9,
    secondMarker: 0,
  },
  /* INTRODUCED by SUNIL_PRESENCE_SPEC.md §4 — no prototype reference exists. The energy is in
     the instrumentation, not the core: everything scans faster, the sphere barely swells. */
  thinking: {
    rotSpeed: 0.62,
    pulseAmp: 0.035,
    pulseFreq: 3.2,
    glowAlpha: 0.16,
    twinkleFreq: 3.6,
    arcSpeedMultiplier: 2.4,
    arcAlphaDelta: 0.08,
    orbitSpeed: 1.8,
    secondMarker: 1,
  },
  /* The inversion of `thinking`: the core throbs, the instrumentation stays at idle speed. */
  speaking: {
    rotSpeed: 0.28,
    pulseAmp: 0.1,
    pulseFreq: 9.0,
    glowAlpha: 0.2,
    twinkleFreq: 2.0,
    arcSpeedMultiplier: 1.0,
    arcAlphaDelta: 0,
    orbitSpeed: 0.9,
    secondMarker: 0,
  },
};

/** The `level` prop maps to `PULSE_AMP = 0.04 + 0.08 × clamp(level,0,1)` (§4.2). */
export const LEVEL_PULSE_BASE = 0.04;
export const LEVEL_PULSE_RANGE = 0.08;

/** Accessible status sentences (§8.3). Plain language, present tense, no jargon. */
export const PRESENCE_STATUS_SENTENCES: Readonly<Record<PresenceState, string>> = {
  idle: "SUNIL is idle.",
  thinking: "SUNIL is working.",
  speaking: "SUNIL is speaking.",
};

/** The visible caption beneath the canvas (PORTAL_SHELL_SPEC.md §8.3). */
export const PRESENCE_CAPTIONS: Readonly<Record<PresenceState, string>> = {
  idle: "STATE · IDLE",
  thinking: "STATE · WORKING",
  speaking: "STATE · SPEAKING",
};

/** One polite announcement per settled state change (§8.3). */
export const ANNOUNCE_DEBOUNCE_MS = 500;
