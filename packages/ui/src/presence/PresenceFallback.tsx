/**
 * The static SVG fallback — SUNIL_PRESENCE_SPEC.md §9.1.
 *
 * Rendered when `getContext('2d')` returns null, when the canvas context is lost, or when the
 * frame loop throws. Same tokens, same proportions, `aria-hidden`. The `.sr-only` status
 * sentence and the visible caption are unaffected, which is the whole point of §8.3: the state
 * is still communicated when the graphics fail.
 *
 * The dot positions are the same fibonacci projection as the canvas, evaluated ONCE when this
 * module is first loaded (not per render and not per frame), at the reduced-motion `t = 1.9`
 * so the fallback and the reduced-motion canvas frame show the same composition.
 */
import type { JSX } from "react";
import {
  AXIS_TILT,
  GOLDEN_ANGLE,
  ORBIT_RX,
  ORBIT_RY,
  ORBIT_TILT,
  PERSPECTIVE_STRENGTH,
  POINT_ALPHA_BASE,
  POINT_ALPHA_RANGE,
  POINT_SIZE_BASE,
  POINT_SIZE_RANGE,
  REDUCED_MOTION_T,
  SPHERE_RADIUS_RATIO,
  STATE_PARAMS,
  ARCS,
} from "./constants.js";

const VIEWBOX = 100;
const FALLBACK_POINTS = 120;

interface FallbackDot {
  readonly cx: number;
  readonly cy: number;
  readonly r: number;
  readonly opacity: number;
}

function computeDots(): FallbackDot[] {
  const dots: FallbackDot[] = [];
  const cx = VIEWBOX / 2;
  const cy = VIEWBOX / 2 - VIEWBOX * 0.045;
  const radius = VIEWBOX * SPHERE_RADIUS_RATIO;
  const rot = REDUCED_MOTION_T * STATE_PARAMS.idle.rotSpeed;
  const cosR = Math.cos(rot);
  const sinR = Math.sin(rot);
  const cosT = Math.cos(AXIS_TILT);
  const sinT = Math.sin(AXIS_TILT);

  for (let i = 0; i < FALLBACK_POINTS; i += 1) {
    const y = 1 - (i / (FALLBACK_POINTS - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const th = GOLDEN_ANGLE * i;
    const x = Math.cos(th) * r;
    const z = Math.sin(th) * r;
    const x1 = x * cosR + z * sinR;
    const z1 = -x * sinR + z * cosR;
    const y2 = y * cosT - z1 * sinT;
    const z2 = y * sinT + z1 * cosT;
    const persp = 1 / (1 - z2 * PERSPECTIVE_STRENGTH);
    const front = (z2 + 1) / 2;
    dots.push({
      cx: cx + x1 * radius * persp,
      cy: cy + y2 * radius * persp,
      r: (POINT_SIZE_BASE + front * POINT_SIZE_RANGE) * (VIEWBOX / 320),
      opacity: POINT_ALPHA_BASE + front * POINT_ALPHA_RANGE,
    });
  }
  return dots;
}

const DOTS = computeDots();
const CENTRE = VIEWBOX / 2;
const CENTRE_Y = VIEWBOX / 2 - VIEWBOX * 0.045;
const SPHERE_R = VIEWBOX * SPHERE_RADIUS_RATIO;

export function PresenceFallback({ className }: { className?: string }): JSX.Element {
  return (
    <svg
      className={className}
      viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}
      aria-hidden="true"
      focusable="false"
    >
      {ARCS.map((arc, index) => (
        <circle
          key={arc.radius}
          cx={CENTRE}
          cy={CENTRE_Y}
          r={SPHERE_R * arc.radius}
          fill="none"
          stroke="var(--sunil-presence-arc)"
          strokeOpacity={arc.alpha}
          strokeWidth={arc.width * (VIEWBOX / 320)}
          strokeDasharray={`${arc.dash[0] * (VIEWBOX / 320)} ${arc.dash[1] * (VIEWBOX / 320)}`}
          transform={`rotate(${index * 24} ${CENTRE} ${CENTRE_Y})`}
        />
      ))}
      <ellipse
        cx={0}
        cy={0}
        rx={SPHERE_R * ORBIT_RX}
        ry={SPHERE_R * ORBIT_RY}
        fill="none"
        stroke="var(--sunil-presence-arc)"
        strokeOpacity={0.4}
        strokeWidth={VIEWBOX / 320}
        transform={`translate(${CENTRE} ${CENTRE_Y}) rotate(${(ORBIT_TILT * 180) / Math.PI})`}
      />
      {DOTS.map((dot, index) => (
        <circle
          key={index}
          cx={dot.cx}
          cy={dot.cy}
          r={dot.r}
          fill="var(--sunil-presence-point)"
          fillOpacity={dot.opacity}
        />
      ))}
      <circle
        cx={CENTRE + Math.cos(REDUCED_MOTION_T * 0.9) * SPHERE_R * ORBIT_RX}
        cy={CENTRE_Y + Math.sin(REDUCED_MOTION_T * 0.9) * SPHERE_R * ORBIT_RY}
        r={3.4 * (VIEWBOX / 320)}
        fill="var(--sunil-presence-marker)"
      />
    </svg>
  );
}
