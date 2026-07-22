/**
 * Root layout.
 *
 * FR-103: the token stylesheet is imported HERE, before any component CSS, so the first paint
 * is already the dark theme — there is no unstyled or light flash to avoid, because there is
 * no moment at which the tokens are absent. `data-theme="dark"` is set on `<html>` for the
 * same reason: it is in the markup the server sends, not applied by a script afterwards.
 *
 * `lang="en-AU"` matches A-13 (en-AU only in Phase 1) and is what a screen reader uses to pick
 * a voice.
 */
import "@sunil/ui/styles.css";
import type { JSX, ReactNode } from "react";
import type { Metadata, Viewport } from "next";
import { BRAND_COLORS } from "@sunil/ui";

export const metadata: Metadata = {
  title: {
    default: "SUNIL",
    template: "%s · SUNIL",
  },
  description: "Systems Utility & Neural Intelligence Liaison.",
  // The portal is a private, single-owner application; there is nothing here to index.
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  // `color-scheme: dark` is also set in `tokens.css` (§8.4) so native scrollbars and form
  // controls follow the theme.
  colorScheme: "dark",
  // Sourced from the token package, not typed as a literal: FR-100 permits no brand colour
  // outside the token definitions, and the browser chrome is not an exception.
  themeColor: BRAND_COLORS.bg,
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: ReactNode }): JSX.Element {
  return (
    <html lang="en-AU" data-theme="dark">
      <body>{children}</body>
    </html>
  );
}
