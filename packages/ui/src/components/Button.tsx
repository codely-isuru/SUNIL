"use client";

/**
 * Button — PORTAL_SHELL_SPEC.md §13, "Button (all variants)".
 *
 * The loading contract is the interesting part and it is spelled out in the spec:
 *   - `aria-busy`, a spinner replaces the leading glyph, and the label becomes the present
 *     participle (`ACCESS` → `AUTHENTICATING`);
 *   - the width is FROZEN while busy so the page does not shift under the pointer;
 *   - success is signalled by the PAGE, never by the button;
 *   - errors appear in the alert region, never inside the button.
 *
 * A submit button is never disabled pending validation (§7.1): disabling it hides the reason
 * for the block. `disabled` here is for genuinely unavailable actions only, such as a Settings
 * section with no unsaved changes.
 */
import { useRef } from "react";
import type { ButtonHTMLAttributes, JSX, ReactNode } from "react";
import { Spinner } from "./primitives.js";

export type ButtonVariant = "primary" | "ghost" | "text";

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  variant?: ButtonVariant;
  block?: boolean;
  tall?: boolean;
  busy?: boolean;
  /** Shown in place of `children` while `busy`. */
  busyLabel?: ReactNode;
  className?: string;
}

export function Button({
  variant = "primary",
  block = false,
  tall = false,
  busy = false,
  busyLabel,
  children,
  className,
  type = "button",
  ...rest
}: ButtonProps): JSX.Element {
  const ref = useRef<HTMLButtonElement | null>(null);
  const frozenWidth = useRef<number | undefined>(undefined);

  if (busy && frozenWidth.current === undefined && ref.current) {
    frozenWidth.current = ref.current.getBoundingClientRect().width;
  }
  if (!busy) frozenWidth.current = undefined;

  const classes = ["sunil-btn", `sunil-btn--${variant}`, "sunil-type-action"];
  if (block) classes.push("sunil-btn--block");
  if (tall) classes.push("sunil-btn--tall");
  if (className) classes.push(className);

  return (
    <button
      {...rest}
      ref={ref}
      type={type}
      className={classes.join(" ")}
      aria-busy={busy ? true : undefined}
      style={frozenWidth.current === undefined ? undefined : { width: frozenWidth.current }}
    >
      {busy ? <Spinner /> : null}
      {busy && busyLabel !== undefined ? busyLabel : children}
    </button>
  );
}
