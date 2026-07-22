"use client";

/**
 * Invitation acceptance — PORTAL_SHELL_SPEC.md §7.3, FR-021 / FR-104.
 *
 * ───────────────────────────────────────────────────────────────────────────────────────────
 * TWO PIECES OF THIS SCREEN NEED AN API ROUTE THAT PHASE1_ARCHITECTURE §13 DOES NOT DEFINE,
 * AND THEY HAVE NOT BEEN INVENTED HERE.
 *
 *   1. §7.3's LOADING state — "Never render the form before the token is validated" — needs a
 *      public `GET /api/invitations/:token` returning `{email}` for a valid token and a generic
 *      400 otherwise. §13 lists only `POST /invitations/:token/accept`.
 *   2. §7.3's live policy checklist — "rules render from the server-supplied policy, never
 *      hard-coded in the UI", so FR-030's configurable minimum stays in one place — needs that
 *      same response (or a public policy endpoint) to carry the rule list.
 *
 * Rather than fabricate either, this screen renders the form immediately and states the policy
 * situation honestly. `PasswordPolicyChecklist` below is complete and prop-driven: when the
 * route exists, pass `rules` and the live checklist appears with no other change. This is
 * recorded in the handover as an outstanding cross-team item, not silently absorbed.
 * ───────────────────────────────────────────────────────────────────────────────────────────
 *
 * The failure copy is IDENTICAL for consumed, expired and mutated tokens (FR-021): the page
 * must not disclose whether the invitation ever existed. And there is no auto-redirect on
 * success — the user just set a credential and should see it succeed (§7.3).
 */
import { useRef, useState } from "react";
import type { FormEvent, JSX } from "react";
import { Alert, Button, Field, Panel } from "@sunil/ui";
import { acceptInvitation } from "../lib/api/client";

export interface PasswordPolicyRule {
  readonly id: string;
  readonly label: string;
  readonly test: (value: string) => boolean;
}

type Screen = "form" | "success" | "invalid";

const INVALID_HEADLINE = "This invitation link is not valid.";
const INVALID_DETAIL = "Ask the system owner for a new invitation.";

/**
 * The live checklist (§7.3). `aria-live="polite"` on the LIST, updating on input — one region
 * for the whole list rather than one per rule, so a user typing hears "3 of 4 met" rather than
 * four interleaved announcements.
 */
export function PasswordPolicyChecklist({
  rules,
  value,
}: {
  rules: readonly PasswordPolicyRule[];
  value: string;
}): JSX.Element {
  return (
    <ul className="sunil-list sunil-type-caption" aria-live="polite">
      {rules.map((rule) => {
        const met = rule.test(value);
        return (
          <li className="sunil-list__row" key={rule.id}>
            <span aria-hidden="true">{met ? "✓" : "○"}</span>
            <span className="sunil-list__row-label">{rule.label}</span>
            <span className="sunil-sr-only">{met ? "met" : "not met"}</span>
          </li>
        );
      })}
    </ul>
  );
}

export function InviteForm({
  token,
  rules,
}: {
  token: string;
  /** Supplied once the API can return the configured policy. Undefined → no checklist. */
  rules?: readonly PasswordPolicyRule[];
}): JSX.Element {
  const [screen, setScreen] = useState<Screen>("form");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const alertRef = useRef<HTMLDivElement | null>(null);

  const mismatch = confirm !== "" && confirm !== password;

  async function onSubmit(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (mismatch) return;
    setBusy(true);
    setMessage("");

    const result = await acceptInvitation(token, password);
    setBusy(false);

    if (result.ok) {
      setScreen("success");
      return;
    }
    if (result.kind === "timeout" || result.kind === "network") {
      setMessage("The server did not respond.");
      requestAnimationFrame(() => alertRef.current?.focus());
      return;
    }
    // Consumed, expired, mutated — one message, no existence disclosure (FR-021).
    setScreen("invalid");
  }

  if (screen === "invalid") {
    return (
      <Panel>
        <p className="sunil-type-body">{INVALID_HEADLINE}</p>
        <p className="sunil-type-caption sunil-fg-secondary">{INVALID_DETAIL}</p>
      </Panel>
    );
  }

  if (screen === "success") {
    return (
      <>
        <p className="sunil-type-body">Your account is ready.</p>
        <a className="sunil-btn sunil-btn--primary sunil-btn--block sunil-type-action" href="/sign-in">
          Sign in
        </a>
      </>
    );
  }

  return (
    <>
      {message === "" ? null : (
        <div ref={alertRef} tabIndex={-1}>
          <Alert>{message}</Alert>
        </div>
      )}

      <form
        className="sunil-auth__form"
        onSubmit={(event) => {
          void onSubmit(event);
        }}
        noValidate
      >
        <Field
          label="New password"
          type="password"
          autoComplete="new-password"
          required
          revealable
          readOnly={busy}
          value={password}
          onChange={(event) => {
            setPassword(event.target.value);
          }}
        />
        {rules === undefined ? (
          <p className="sunil-type-caption sunil-fg-secondary">
            Your password must meet the system password policy. The policy is applied by the
            server when you submit.
          </p>
        ) : (
          <PasswordPolicyChecklist rules={rules} value={password} />
        )}
        <Field
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          required
          readOnly={busy}
          error={mismatch ? "The two passwords do not match." : undefined}
          value={confirm}
          onChange={(event) => {
            setConfirm(event.target.value);
          }}
        />
        <Button type="submit" block tall busy={busy} busyLabel="Creating access">
          Create access
        </Button>
      </form>
    </>
  );
}
