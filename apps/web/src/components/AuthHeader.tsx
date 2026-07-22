/**
 * The wordmark block shared by the three auth screens (PORTAL_SHELL_SPEC.md §7).
 *
 * Exactly one `<h1>` per page (§3). On sign-in the wordmark IS the page's heading; on the MFA
 * and invitation screens §7.2/§7.3 give the page a heading of its own, so there the wordmark
 * steps down to a paragraph rather than producing a second `<h1>` or a skipped level.
 */
import type { JSX } from "react";

export function AuthHeader({ heading }: { heading?: string }): JSX.Element {
  return (
    <div>
      {heading === undefined ? (
        <h1 className="sunil-auth__wordmark sunil-type-display-lg">S.U.N.I.L</h1>
      ) : (
        <p className="sunil-auth__wordmark sunil-type-display-lg">S.U.N.I.L</p>
      )}
      <p className="sunil-auth__subtitle sunil-type-micro">
        Systems Utility &amp; Neural Intelligence Liaison
      </p>
      {heading === undefined ? null : (
        <h1 className="sunil-auth__heading sunil-type-title">{heading}</h1>
      )}
    </div>
  );
}
