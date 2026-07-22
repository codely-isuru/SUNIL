/**
 * `/sign-in` — PORTAL_SHELL_SPEC.md §7.1.
 *
 * `PHASE1_ARCHITECTURE` §14 calls this route `/login`; the design spec calls it `/sign-in`.
 * The design spec is implemented and `/login` redirects here (see `next.config.mjs`), so a
 * link written against either document works and neither document has to be wrong.
 */
import type { JSX } from "react";
import type { Metadata } from "next";
import { AuthHeader } from "../../../components/AuthHeader";
import { SignInForm } from "../../../components/SignInForm";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage(): JSX.Element {
  return (
    <>
      <AuthHeader />
      <SignInForm />
    </>
  );
}
