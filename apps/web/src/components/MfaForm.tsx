"use client";

/**
 * MFA / TOTP challenge — PORTAL_SHELL_SPEC.md §7.2, FR-027.
 *
 * ONE input, not six boxes. Six boxes break paste, break `one-time-code` autofill, break
 * mobile keyboards and create six tab stops for one value; a single tracked input looks
 * identical and works. That decision is the spec's, and it is restated here because "six
 * pretty boxes" is the thing a reviewer will ask for.
 *
 * The error message is identical for an invalid code and a REPLAYED one. §6.4 stores the
 * accepted timestep and rejects anything at or below it; FR-027 audits the difference. The
 * user is not told which happened.
 */
import { useEffect, useRef, useState } from "react";
import type { FormEvent, JSX } from "react";
import { useRouter } from "next/navigation";
import { Alert, Button, Field } from "@sunil/ui";
import { verifyMfa } from "../lib/api/client";
import {
  clearPendingCsrfToken,
  hasPendingCsrfToken,
  readPendingCsrfToken,
} from "../lib/session/pendingAuth";

type Mode = "totp" | "recovery";
type FormState = "empty" | "loading" | "error";

const INVALID = "That code is not valid. Try the next code from your app.";
const NO_RESPONSE = "The server did not respond.";
const AUTO_SUBMIT_SETTLE_MS = 250;

export function MfaForm(): JSX.Element {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("totp");
  const [state, setState] = useState<FormState>("empty");
  const [code, setCode] = useState("");
  const [message, setMessage] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const alertRef = useRef<HTMLDivElement | null>(null);
  const submittingRef = useRef(false);

  async function submit(value: string): Promise<void> {
    if (submittingRef.current) return;
    submittingRef.current = true;
    setState("loading");
    setMessage("");

    // `/auth/mfa/verify` mutates a PENDING_MFA session, so it carries the CSRF token issued at
    // login (ADR-009 / amendment A2). Both the session token and the CSRF secret ROTATE on
    // elevation (§6.2), so nothing downstream reuses this one: the shell re-reads the current
    // token from `GET /auth/me`.
    const result = await verifyMfa(
      mode === "totp" ? { code: value } : { recoveryCode: value },
      readPendingCsrfToken() ?? undefined,
    );
    submittingRef.current = false;

    if (result.ok) {
      clearPendingCsrfToken();
      setAnnouncement("Verified. Dashboard.");
      router.push("/");
      return;
    }

    setState("error");
    setCode("");
    if (result.kind === "forbidden" && !hasPendingCsrfToken()) {
      // A hard reload of this route loses the in-memory CSRF token from login, so no code can
      // succeed. That is a broken flow, not a bad code, and saying "that code is not valid"
      // would send the user to fetch code after code from their authenticator for nothing.
      setMessage("Your sign-in session was interrupted. Sign in again to continue.");
    } else if (result.kind === "rate_limited") {
      const minutes = Math.max(1, Math.ceil((result.retryAfterSeconds ?? 900) / 60));
      setMessage(`Too many attempts. Try again in ${minutes} minutes.`);
    } else if (result.kind === "timeout" || result.kind === "network") {
      setMessage(NO_RESPONSE);
    } else {
      setMessage(INVALID);
    }
    requestAnimationFrame(() => {
      alertRef.current?.focus();
      inputRef.current?.focus();
    });
  }

  // Auto-submit on the 6th digit after a 250ms settle. The manual button always remains —
  // an auto-submit that is the ONLY way to submit is a trap when autofill misfires.
  useEffect(() => {
    if (mode !== "totp" || code.length !== 6 || state === "loading") return undefined;
    const timer = setTimeout(() => {
      void submit(code);
    }, AUTO_SUBMIT_SETTLE_MS);
    return () => {
      clearTimeout(timer);
    };
    // `submit` is stable enough for this effect's purpose: it closes over `mode`, which is in
    // the dependency list, and over refs.
  }, [code, mode, state]);

  const busy = state === "loading";

  return (
    <>
      {state === "error" ? (
        <div ref={alertRef} tabIndex={-1}>
          <Alert>{message}</Alert>
        </div>
      ) : null}

      <p className="sunil-type-body sunil-fg-secondary">
        {mode === "totp"
          ? "Enter the 6-digit code from your authenticator app."
          : "Enter one of your recovery codes."}
      </p>

      <form
        className="sunil-auth__form"
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          void submit(code);
        }}
        noValidate
      >
        {mode === "totp" ? (
          <Field
            key="totp"
            label="Verification code"
            inputMode="numeric"
            pattern="[0-9]*"
            maxLength={6}
            autoComplete="one-time-code"
            autoFocus
            required
            readOnly={busy}
            inputRef={inputRef}
            inputClassName="sunil-field__input--code"
            hint="Codes refresh every 30 seconds."
            error={state === "error" ? message : undefined}
            value={code}
            onChange={(event) => {
              setCode(event.target.value.replace(/\D/g, "").slice(0, 6));
            }}
          />
        ) : (
          <Field
            key="recovery"
            label="Recovery code"
            type="text"
            autoComplete="off"
            maxLength={16}
            autoFocus
            required
            readOnly={busy}
            inputRef={inputRef}
            error={state === "error" ? message : undefined}
            value={code}
            onChange={(event) => {
              setCode(event.target.value.trim());
            }}
          />
        )}

        <Button type="submit" block tall busy={busy} busyLabel="Verifying">
          Verify
        </Button>
      </form>

      <Button
        variant="text"
        onClick={() => {
          setMode(mode === "totp" ? "recovery" : "totp");
          setCode("");
          setState("empty");
        }}
      >
        {mode === "totp" ? "Use a recovery code instead" : "Use an authenticator code"}
      </Button>

      <a className="sunil-type-caption" href="/sign-in">
        Cancel and sign out
      </a>

      <div role="status" aria-live="polite" className="sunil-sr-only">
        {announcement}
      </div>
    </>
  );
}
