"use client";

import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiError, getSession, login } from "@/lib/api";

/**
 * The login screen itself is explicitly out of scope for
 * `M1_CHAT_SPEC.md` ("mechanism is the Architect's call per SRS Open
 * Question Q3") — no Designer copy or visual spec exists for this screen.
 * This is a minimal, functional form built from the same design-system
 * tokens as everything else (colours, radii, type scale), not a Designer-
 * authored screen. Single-user, session-based login per SRS Q3's adopted
 * default — no signup/invite flow.
 */
export default function LoginPage() {
  const router = useRouter();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSession()
      .then((session) => {
        if (!cancelled && session.authenticated) router.replace("/");
      })
      .catch(() => {
        // No session / API not reachable yet — stay on the login form.
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
      router.replace("/");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("Incorrect username or password.");
      } else if (err instanceof ApiError && err.status === 429) {
        setError("Too many attempts. Try again in a moment.");
      } else {
        setError("Couldn't sign in right now. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-canvas px-4">
      <div className="w-full max-w-sm rounded-md border border-border-accent bg-surface p-6 shadow-glow-hover">
        <h1 className="mb-1 font-display text-h1 uppercase tracking-h1 text-text-primary">S.U.N.I.L</h1>
        <p className="mb-6 font-mono-body text-small text-text-muted">Sign in to continue.</p>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="font-mono-ui text-micro uppercase tracking-micro text-text-secondary">
              Username
            </span>
            <input
              type="text"
              autoComplete="username"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="rounded-md border border-border bg-surface-raised px-3 py-2 font-mono-body text-body text-text-primary focus-visible:border-border-strong"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="font-mono-ui text-micro uppercase tracking-micro text-text-secondary">
              Password
            </span>
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="rounded-md border border-border bg-surface-raised px-3 py-2 font-mono-body text-body text-text-primary focus-visible:border-border-strong"
            />
          </label>

          {error && (
            <p role="alert" className="font-mono-body text-small text-danger">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-2 min-h-11 rounded-md bg-accent px-4 py-2 font-mono-body text-small font-semibold text-accent-on transition-colors duration-fast ease-standard hover:bg-accent-hover active:bg-accent-active disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </main>
  );
}
