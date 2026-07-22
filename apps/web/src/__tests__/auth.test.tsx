/**
 * The auth screens — PORTAL_SHELL_SPEC.md §7, FR-020 / FR-022 / FR-104 / NFR-016.
 *
 * These assert the SHAPE of the pages, which is where the security-relevant decisions live:
 * one generic failure message, no registration affordance, `autocomplete` on every field,
 * visible labels, and a submit that is never disabled pending validation.
 */
import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

vi.mock("next/navigation", () => ({
  usePathname: () => "/sign-in",
  useRouter: () => ({ push: () => undefined, replace: () => undefined }),
}));

const { SignInForm } = await import("../components/SignInForm");
const { MfaForm } = await import("../components/MfaForm");
const { InviteForm, PasswordPolicyChecklist } = await import("../components/InviteForm");
const { AuthHeader } = await import("../components/AuthHeader");

function countOf(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

/**
 * HTML attribute names are case-insensitive and React 19 emits several of them in the React
 * prop casing (`maxLength`, `inputMode`, `autoComplete`). The browser lowercases them while
 * parsing, so attribute assertions are made against a lowercased copy of the markup.
 */
function attrs(html: string): string {
  return html.toLowerCase();
}

describe("sign-in (§7.1)", () => {
  const html = renderToStaticMarkup(
    <>
      <AuthHeader />
      <SignInForm />
    </>,
  );

  it("labels both fields visibly and associates them with <label for>", () => {
    expect(countOf(html, "<label")).toBe(2);
    expect(html).toContain(">Email");
    expect(html).toContain(">Password");
    expect(countOf(attrs(html), "for=")).toBe(2);
  });

  it("sets the autocomplete tokens a password manager needs (SC 1.3.5)", () => {
    expect(attrs(html)).toContain('autocomplete="username"');
    expect(attrs(html)).toContain('autocomplete="current-password"');
  });

  it("never disables the submit button pending validation", () => {
    expect(html).toContain('type="submit"');
    expect(html).not.toContain("disabled");
  });

  it("offers NO registration path of any kind (FR-020)", () => {
    for (const forbidden of ["Sign up", "Create account", "Register", "Continue with Google"]) {
      expect(html).not.toContain(forbidden);
    }
    expect(html).toContain("Access is by invitation only.");
  });

  it("omits 'forgot password', because no recovery flow exists in Phase 1 (§7.1, S-1)", () => {
    expect(html.toLowerCase()).not.toContain("forgot");
  });

  it("gives the password reveal an accessible name and a pressed state (§11.4)", () => {
    expect(html).toContain('aria-label="Show password"');
    expect(html).toContain('aria-pressed="false"');
  });

  it("renders exactly one <h1> — the wordmark", () => {
    expect(countOf(html, "<h1")).toBe(1);
    expect(html).toContain("S.U.N.I.L");
  });

  it("shows no error text until something fails", () => {
    expect(html).not.toContain("Sign-in failed");
    expect(html).not.toContain('role="alert"');
  });
});

describe("MFA challenge (§7.2)", () => {
  const html = renderToStaticMarkup(
    <>
      <AuthHeader heading="Verification required" />
      <MfaForm />
    </>,
  );

  it("uses ONE input, not six boxes", () => {
    expect(countOf(html, "<input")).toBe(1);
    expect(attrs(html)).toContain('maxlength="6"');
    expect(attrs(html)).toContain('inputmode="numeric"');
    expect(attrs(html)).toContain('autocomplete="one-time-code"');
  });

  it("keeps a manual submit alongside the auto-submit", () => {
    expect(html).toContain('type="submit"');
    expect(html).toContain("Verify");
  });

  it("offers the recovery-code path and a way out", () => {
    expect(html).toContain("Use a recovery code instead");
    expect(html).toContain("Cancel and sign out");
  });

  it("puts its own <h1> on the page and steps the wordmark down to a paragraph", () => {
    expect(countOf(html, "<h1")).toBe(1);
    expect(html).toContain("Verification required");
  });

  it("tells the user codes rotate, without telling them why a code failed", () => {
    expect(html).toContain("Codes refresh every 30 seconds.");
    expect(html).not.toContain("reused");
    expect(html).not.toContain("replay");
  });
});

describe("invitation acceptance (§7.3, FR-021)", () => {
  const html = renderToStaticMarkup(<InviteForm token="opaque-token" />);

  it("asks for a password and a confirmation, both with new-password autocomplete", () => {
    expect(countOf(attrs(html), 'autocomplete="new-password"')).toBe(2);
  });

  it("does not echo the token into the rendered page", () => {
    expect(html).not.toContain("opaque-token");
  });

  it("states the policy honestly when the API cannot supply it", () => {
    expect(html).toContain("system password policy");
  });

  it("renders a live checklist when rules ARE supplied", () => {
    const withRules = renderToStaticMarkup(
      <PasswordPolicyChecklist
        rules={[
          { id: "len", label: "At least 12 characters", test: (v) => v.length >= 12 },
          { id: "num", label: "Contains a number", test: (v) => /\d/.test(v) },
        ]}
        value="short1"
      />,
    );
    expect(withRules).toContain('aria-live="polite"');
    expect(withRules).toContain("At least 12 characters");
    expect(countOf(withRules, "not met")).toBe(1);
    expect(countOf(withRules, ">met<")).toBe(1);
  });
});
