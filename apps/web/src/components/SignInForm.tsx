"use client";

/**
 * Sign-in — PORTAL_SHELL_SPEC.md §7.1 and §13, FR-104 / FR-022 / FR-029.
 *
 * The rules that are easy to get wrong, and are therefore implemented explicitly:
 *
 *   - ONE generic failure message for wrong password, unknown email, disabled account and
 *     expired invitation alike. Anything that varies with the reason is an account-existence
 *     oracle (FR-022). The single exception is the lockout message, because the user genuinely
 *     cannot proceed and the lockout applies regardless of whether the account exists (FR-029).
 *   - The submit button is NEVER disabled pending validation: disabling it hides the reason for
 *     the block.
 *   - Fields go `readonly` while submitting, not `disabled` — a disabled field loses its
 *     accessible name in some assistive technology.
 *   - A 10s watchdog moves to the error state with "The server did not respond." (the client's
 *     default timeout produces the `timeout` category).
 *   - On failure the password is cleared and re-focused, the email keeps its value, and focus
 *     moves to the alert so the message is announced rather than merely displayed.
 *   - No "create account" affordance of any kind (FR-020), and no "forgot password" link,
 *     because no recovery path and no mail transport exist in Phase 1 (A-03, §7.1, S-1).
 */
import { useRef, useState } from "react";
import type { FormEvent, JSX } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Field } from "@sunil/ui";
import { login } from "../lib/api/client";
import { setPendingCsrfToken } from "../lib/session/pendingAuth";

type FormState = "empty" | "loading" | "error";

const GENERIC_FAILURE = "Sign-in failed. Check your email and password.";
const NO_RESPONSE = "The server did not respond.";

export function SignInForm(): JSX.Element {
  const router = useRouter();
  const [state, setState] = useState<FormState>("empty");
  const [message, setMessage] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const alertRef = useRef<HTMLDivElement | null>(null);
  const passwordRef = useRef<HTMLInputElement | null>(null);

  function fail(text: string): void {
    setState("error");
    setMessage(text);
    setPassword("");
    // Focus the alert so it is read, then hand focus to the field that must be retyped.
    requestAnimationFrame(() => {
      alertRef.current?.focus();
      passwordRef.current?.focus();
    });
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    setState("loading");
    setMessage("");

    const result = await login(email, password);

    if (result.ok) {
      // `/auth/mfa/verify` is a mutating request on a PENDING_MFA session, so the CSRF token
      // issued here has to travel to the MFA screen (ADR-009 / A2). In memory only — never
      // storage (§11.8, and see `pendingAuth.ts`).
      setPendingCsrfToken(result.data.csrfToken);
      setAnnouncement(result.data.mfaRequired ? "Verification required." : "Signed in. Dashboard.");
      router.push(result.data.mfaRequired ? "/sign-in/mfa" : "/");
      return;
    }

    if (result.kind === "timeout" || result.kind === "network") {
      fail(NO_RESPONSE);
      return;
    }
    if (result.kind === "rate_limited") {
      const minutes = Math.max(1, Math.ceil((result.retryAfterSeconds ?? 900) / 60));
      fail(`Too many attempts. Try again in ${minutes} minutes.`);
      return;
    }
    fail(GENERIC_FAILURE);
  }

  const busy = state === "loading";

  return (
    <>
      {state === "error" ? (
        <div ref={alertRef} tabIndex={-1}>
          <Alert>{message}</Alert>
        </div>
      ) : null}

      <form
        className="sunil-auth__form"
        onSubmit={(event) => {
          void onSubmit(event);
        }}
        noValidate
      >
        <Field
          label="Email"
          type="email"
          inputMode="email"
          autoComplete="username"
          name="email"
          required
          autoFocus
          readOnly={busy}
          value={email}
          onChange={(event) => {
            setEmail(event.target.value);
          }}
        />
        <Field
          label="Password"
          type="password"
          autoComplete="current-password"
          name="password"
          required
          revealable
          readOnly={busy}
          inputRef={passwordRef}
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
        />
        <Button type="submit" block tall busy={busy} busyLabel="Authenticating">
          Access
        </Button>
      </form>

      <p className="sunil-auth__footer sunil-type-caption">Access is by invitation only.</p>

      <div role="status" aria-live="polite" className="sunil-sr-only">
        {announcement}
      </div>
    </>
  );
}
