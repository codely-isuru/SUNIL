/**
 * `/invite/[token]` — PORTAL_SHELL_SPEC.md §7.3.
 *
 * The token is a path parameter and is never logged, never echoed into the page beyond the
 * form's submission, and never placed in a query string (§11.8 / privacy).
 */
import type { JSX } from "react";
import type { Metadata } from "next";
import { AuthHeader } from "../../../../components/AuthHeader";
import { InviteForm } from "../../../../components/InviteForm";

export const metadata: Metadata = { title: "Set your password" };

export default async function InvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}): Promise<JSX.Element> {
  const { token } = await params;
  return (
    <>
      <AuthHeader heading="Set your password" />
      <InviteForm token={token} />
    </>
  );
}
