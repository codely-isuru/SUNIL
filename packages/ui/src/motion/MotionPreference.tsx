"use client";

/**
 * The resolved motion decision, supplied by the shell.
 *
 * PORTAL_SHELL_SPEC.md §11.6 / SUNIL_PRESENCE_SPEC.md §8.2: the Settings → Appearance "Motion"
 * control **overrides** `prefers-reduced-motion` in both directions, and its default is
 * "Follow system". Components receive the decision from this provider rather than reading
 * `matchMedia` themselves, so one setting governs the whole app.
 */
import { createContext, createElement, useContext } from "react";
import type { JSX, ReactNode } from "react";

export type MotionPreference = "system" | "reduce" | "no-reduce";

const MotionPreferenceContext = createContext<MotionPreference>("system");

export function MotionPreferenceProvider({
  value,
  children,
}: {
  value: MotionPreference;
  children: ReactNode;
}): JSX.Element {
  return createElement(MotionPreferenceContext.Provider, { value }, children);
}

export function useMotionPreference(): MotionPreference {
  return useContext(MotionPreferenceContext);
}

/**
 * `true` = always reduce, `false` = never reduce, `undefined` = follow the media query.
 * `undefined` is not a missing value: it is the explicit "the OS decides" case, and the
 * presence controller treats it as "read `matchMedia` and subscribe to changes".
 */
export function useResolvedReducedMotion(): boolean | undefined {
  const preference = useMotionPreference();
  if (preference === "reduce") return true;
  if (preference === "no-reduce") return false;
  return undefined;
}
