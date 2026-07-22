"use client";

/**
 * The user menu — PORTAL_SHELL_SPEC.md §4, slot 6.
 *
 * Sign-out is a POST through the API (§13, self-service `logout`), carrying the CSRF token
 * (ADR-009). It is a `<button>`, never a link: a GET that mutates session state is
 * pre-fetchable and CSRF-able.
 *
 * Focus returns to the trigger when the menu closes, and Escape closes it — the two things
 * that make a menu usable without a mouse (§11.2).
 */
import { useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import { useRouter } from "next/navigation";
import { logout } from "../lib/api/client";

export function UserMenu({
  displayName,
  roleLabel,
  csrfToken,
}: {
  displayName: string;
  roleLabel: string;
  csrfToken?: string;
}): JSX.Element {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const panelRef = useRef<HTMLDivElement | null>(null);
  const initial = displayName.trim().charAt(0).toUpperCase() || "?";

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };
    const onPointerDown = (event: MouseEvent): void => {
      if (
        panelRef.current &&
        event.target instanceof Node &&
        !panelRef.current.contains(event.target) &&
        !triggerRef.current?.contains(event.target)
      ) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("mousedown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("mousedown", onPointerDown);
    };
  }, [open]);

  async function signOut(): Promise<void> {
    await logout(csrfToken);
    router.push("/sign-in");
  }

  return (
    <div className="sunil-user-menu">
      <button
        ref={triggerRef}
        type="button"
        className="sunil-user-chip sunil-type-micro"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-label={`Account menu for ${displayName}`}
        onClick={() => {
          setOpen((value) => !value);
        }}
      >
        <span aria-hidden="true">{initial}</span>
      </button>

      {open ? (
        <div ref={panelRef} className="sunil-user-menu__panel" role="menu">
          <div className="sunil-user-menu__identity">
            <p className="sunil-type-body-sm sunil-fg-primary">{displayName}</p>
            <p className="sunil-type-micro sunil-fg-muted">{roleLabel}</p>
          </div>
          <a className="sunil-user-menu__item sunil-type-body-sm" role="menuitem" href="/settings">
            Settings
          </a>
          <button
            type="button"
            role="menuitem"
            className="sunil-user-menu__item sunil-type-body-sm"
            onClick={() => {
              void signOut();
            }}
          >
            Sign out
          </button>
        </div>
      ) : null}
    </div>
  );
}
