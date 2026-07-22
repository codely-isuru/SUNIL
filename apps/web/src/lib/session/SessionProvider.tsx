"use client";

/**
 * The session context: the presentation-safe projection of `GET /api/auth/me`.
 *
 * WHAT IS AND IS NOT IN HERE MATTERS (FR-105, §11.8). This carries a display name, a role
 * label, the permission array and the CSRF token — and nothing else. The session token lives
 * in an httpOnly cookie the client cannot read, no secret, key or fingerprint is ever placed
 * on a component prop, and nothing authentication-related is written to `localStorage`.
 *
 * The CSRF token is not a secret in the FR-042 sense: it is a per-session anti-forgery value
 * that the API hands the client precisely so the client can send it back in `X-CSRF-Token`.
 */
import { createContext, createElement, useContext } from "react";
import type { JSX, ReactNode } from "react";

export interface SessionValue {
  readonly displayName: string;
  readonly roleLabel: string;
  readonly permissions: readonly string[];
  readonly csrfToken?: string;
  /** True when `/auth/me` could not be reached; the UI must degrade honestly, not guess. */
  readonly limited: boolean;
}

const SessionContext = createContext<SessionValue>({
  displayName: "Signed-in user",
  roleLabel: "Role unavailable",
  permissions: [],
  limited: true,
});

export function SessionProvider({
  value,
  children,
}: {
  value: SessionValue;
  children: ReactNode;
}): JSX.Element {
  return createElement(SessionContext.Provider, { value }, children);
}

export function useSession(): SessionValue {
  return useContext(SessionContext);
}
