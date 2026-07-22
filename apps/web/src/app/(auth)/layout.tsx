/**
 * Shared auth layout — PORTAL_SHELL_SPEC.md §7. Used by sign-in, the MFA challenge and
 * invitation acceptance.
 *
 * The card is OPAQUE (`--sunil-surface-solid`), not the translucent panel token, because it
 * sits over the presence canvas and a translucent surface over an animated backdrop has an
 * unmeasurable text contrast ratio (DESIGN_TOKENS.md §5.4.3).
 *
 * `<SunilPresence announce={false}>`: the canvas is decorative here and no page element
 * reports its state, so it must not narrate itself on a sign-in screen.
 */
import type { JSX, ReactNode } from "react";
import { SunilPresence } from "@sunil/ui";

export default function AuthLayout({ children }: { children: ReactNode }): JSX.Element {
  return (
    <div className="sunil-auth">
      {/* §11.1 — the auth pages' tab order starts with the skip link, then the first field.
          There is no navigation landmark here, so there is only one skip link. */}
      <a className="sunil-skip-link sunil-type-body-sm" href="#main">
        Skip to main content
      </a>
      <div className="sunil-auth__canvas" aria-hidden="true">
        <SunilPresence state="idle" size="lg" announce={false} />
      </div>
      <div className="sunil-ambience sunil-scanlines" aria-hidden="true" />
      <div className="sunil-ambience sunil-vignette" aria-hidden="true" />
      <main id="main" className="sunil-main sunil-auth__card sunil-panel" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
