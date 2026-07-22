"use client";

/**
 * `<SunilPresence />` — the product's identity (SUNIL_PRESENCE_SPEC.md).
 *
 * This file is deliberately thin. All of the animation lives in `engine.ts`, which touches no
 * React and no global, so the §5.3 cleanup test can drive it with fake timers. What is left
 * here is exactly three jobs:
 *
 *   1. render the wrapper at its final size on the SERVER (no `window`, no `document`,
 *      no `performance` outside an effect — §9.2), so nothing shifts when the canvas appears;
 *   2. construct one controller per mount and `dispose()` it in the cleanup (FR-102);
 *   3. carry the state as TEXT, because the canvas is `aria-hidden` and conveys state (§8.3).
 */
import { useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import type { PresenceState } from "@sunil/core/tokens";
import { PRESENCE_SIZES } from "../tokens/tokens.js";
import type { PresenceSizeName } from "../tokens/tokens.js";
import { ANNOUNCE_DEBOUNCE_MS, PRESENCE_STATUS_SENTENCES } from "./constants.js";
import { mountPresence } from "./mount.js";
import type {
  PresenceController,
  PresenceFrameInfo,
  PresenceQuality,
} from "./engine.js";
import { browserPresenceEnv } from "./env.js";
import { PresenceFallback } from "./PresenceFallback.js";
import { useResolvedReducedMotion } from "../motion/MotionPreference.js";

export interface SunilPresenceProps {
  /** Visual state. Prop-driven only; the component owns no state machine (FR-102). */
  state?: PresenceState;
  /** `'sm'` 200px | `'md'` 320px | `'lg'` 440px | a number of CSS px (always square). */
  size?: PresenceSizeName | number;
  /** 0..1 speaking amplitude, for future voice output. Ignored unless speaking (§4.2). */
  level?: number;
  /** Point-count / effect tier. `'auto'` picks from the rendered size (§6.2). */
  quality?: PresenceQuality;
  /** Freezes the loop without unmounting (§5.4). */
  paused?: boolean;
  /** Emit state changes to this component's own polite live region (§8.3). */
  announce?: boolean;
  /** Overrides the accessible status sentence. */
  label?: string;
  className?: string;
  /** Test/dev instrumentation only. Called once per rendered frame. */
  onFrame?: (info: PresenceFrameInfo) => void;
}

function resolveSize(size: SunilPresenceProps["size"]): number {
  if (typeof size === "number") return size;
  return PRESENCE_SIZES[size ?? "md"];
}

export function SunilPresence({
  state = "idle",
  size = "md",
  level,
  quality = "auto",
  paused = false,
  announce = true,
  label,
  className,
  onFrame,
}: SunilPresenceProps): JSX.Element {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const controllerRef = useRef<PresenceController | null>(null);
  const [canvasMounted, setCanvasMounted] = useState(false);
  const [fallback, setFallback] = useState(false);
  const [announced, setAnnounced] = useState("");
  const reducedMotion = useResolvedReducedMotion();
  const pixels = resolveSize(size);
  const sentence = label ?? PRESENCE_STATUS_SENTENCES[state];

  // The canvas is client-only (§9.2). The wrapper, the status sentence and the box size are
  // server-rendered, so first paint is already the final size.
  useEffect(() => {
    setCanvasMounted(true);
  }, []);

  useEffect(() => {
    if (!canvasMounted) return undefined;
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return undefined;

    const cleanup = mountPresence({
      canvas,
      env: browserPresenceEnv(host, canvas),
      state,
      quality,
      paused,
      level,
      reducedMotion,
      onFrame,
      onFallback: setFallback,
      onController: (controller) => {
        controllerRef.current = controller;
      },
    });

    return () => {
      cleanup();
      controllerRef.current = null;
    };
    // Intentionally keyed on `canvasMounted` alone. The controller is created ONCE per mount;
    // every other prop is pushed into it through the imperative setters below, because
    // recreating it would reset `t` and teleport the rotation and every twinkle phase (§4.1).
  }, [canvasMounted]);

  useEffect(() => {
    controllerRef.current?.setState(state);
  }, [state]);

  useEffect(() => {
    controllerRef.current?.setPaused(paused);
  }, [paused]);

  useEffect(() => {
    controllerRef.current?.setLevel(level);
  }, [level]);

  useEffect(() => {
    controllerRef.current?.setReducedMotion(reducedMotion);
  }, [reducedMotion]);

  // One polite announcement per SETTLED state change; never on mount (§8.3). Rapid
  // thinking → speaking → thinking flapping announces once, after the 500ms debounce.
  const mountedRef = useRef(false);
  useEffect(() => {
    if (!announce) return undefined;
    if (!mountedRef.current) {
      mountedRef.current = true;
      return undefined;
    }
    const timer = setTimeout(() => {
      setAnnounced(sentence);
    }, ANNOUNCE_DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [announce, sentence]);

  return (
    <div
      ref={hostRef}
      className={className ? `sunil-presence ${className}` : "sunil-presence"}
      style={{ width: pixels, height: pixels }}
    >
      {fallback || !canvasMounted ? (
        <PresenceFallback className="sunil-presence__fallback" />
      ) : null}
      {canvasMounted && !fallback ? (
        // No width/height attributes in the markup: they are set in JS from the measured box,
        // and a stale attribute causes a one-frame wrong-size flash (§7.1).
        <canvas ref={canvasRef} className="sunil-presence__canvas" aria-hidden="true" />
      ) : null}

      {/* Always in the DOM, so a user browsing the page discovers the state without having
          to be present for a change (§8.3). */}
      <p className="sunil-sr-only">{sentence}</p>

      {announce ? (
        <div role="status" aria-live="polite" aria-atomic="true" className="sunil-sr-only">
          {announced}
        </div>
      ) : null}
    </div>
  );
}
