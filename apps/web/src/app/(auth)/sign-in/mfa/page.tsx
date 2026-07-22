/**
 * `/sign-in/mfa` — PORTAL_SHELL_SPEC.md §7.2.
 *
 * Reached only after a correct password when the user is enrolled (FR-027). The session is
 * PENDING_MFA until this passes (§6.2); the API accepts nothing but `/auth/mfa/verify` in that
 * state, which is what makes this screen a gate rather than a formality.
 */
import type { JSX } from "react";
import type { Metadata } from "next";
import { AuthHeader } from "../../../../components/AuthHeader";
import { MfaForm } from "../../../../components/MfaForm";

export const metadata: Metadata = { title: "Verification required" };

export default function MfaPage(): JSX.Element {
  return (
    <>
      <AuthHeader heading="Verification required" />
      <MfaForm />
    </>
  );
}
