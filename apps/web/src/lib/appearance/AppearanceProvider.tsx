"use client";

/**
 * Appearance preferences — PORTAL_SHELL_SPEC.md §9 (Appearance) and §11.6.
 *
 * Two settings, both of which OVERRIDE a media query rather than merely following it:
 *   - Motion: Follow system / Always reduce / Never reduce. It governs `<SunilPresence />`
 *     through `<MotionPreferenceProvider>`, in both directions (SUNIL_PRESENCE_SPEC.md §8.2).
 *   - Ambience: the scanline overlay on/off. Reduced motion does not remove the scanlines —
 *     they are static — so §11.6 requires a manual switch instead.
 *
 * Theme is NOT here: Phase 1 ships dark only (FR-103), and the Settings control for it is a
 * disabled select with a note, not a preference with nowhere to go.
 *
 * These values are held in memory and persisted through `PUT /api/settings/:key` like every
 * other setting. Nothing is written to `localStorage`: §11.8's rule is about authentication
 * state, but a second, silent source of truth for a user preference is its own bug.
 */
import { createContext, useContext, useMemo, useState } from "react";
import type { JSX, ReactNode } from "react";
import { MotionPreferenceProvider } from "@sunil/ui";
import type { MotionPreference } from "@sunil/ui";

export interface AppearanceValue {
  readonly motion: MotionPreference;
  readonly scanlines: boolean;
  setMotion(value: MotionPreference): void;
  setScanlines(value: boolean): void;
}

const AppearanceContext = createContext<AppearanceValue>({
  motion: "system",
  scanlines: true,
  setMotion: () => undefined,
  setScanlines: () => undefined,
});

export function AppearanceProvider({ children }: { children: ReactNode }): JSX.Element {
  const [motion, setMotion] = useState<MotionPreference>("system");
  const [scanlines, setScanlines] = useState(true);
  const value = useMemo<AppearanceValue>(
    () => ({ motion, scanlines, setMotion, setScanlines }),
    [motion, scanlines],
  );

  return (
    <AppearanceContext.Provider value={value}>
      <MotionPreferenceProvider value={motion}>
        <div data-ambience={scanlines ? "on" : "off"}>{children}</div>
      </MotionPreferenceProvider>
    </AppearanceContext.Provider>
  );
}

export function useAppearance(): AppearanceValue {
  return useContext(AppearanceContext);
}
