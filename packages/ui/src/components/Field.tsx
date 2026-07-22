"use client";

/**
 * Field — PORTAL_SHELL_SPEC.md §11.3 and §13 ("Field (all types)").
 *
 * Every rule the spec states about forms is implemented here once, so no page can forget one:
 *   - a real `<label for>`; the label is ALWAYS visible and is never a placeholder;
 *   - required fields carry `required` + `aria-required` AND the word "Required" in the label,
 *     because an asterisk alone is not an accessible convention;
 *   - errors set `aria-invalid`, are linked with `aria-describedby`, and are stated in WORDS —
 *     the border colour is corroboration, never the message (SC 1.4.1, SC 3.3.1);
 *   - a placeholder is a format example only.
 *
 * The password show/hide toggle is one of only two icon-only controls in Phase 1 (§11.4), so it
 * carries an `aria-label` and `aria-pressed`, and toggling does not move focus.
 */
import { useId, useState } from "react";
import type { InputHTMLAttributes, JSX, ReactNode, Ref } from "react";

export interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "id" | "className"> {
  label: string;
  hint?: ReactNode;
  error?: ReactNode;
  /** Adds a show/hide toggle. Only meaningful with `type="password"`. */
  revealable?: boolean;
  inputClassName?: string;
  inputRef?: Ref<HTMLInputElement>;
}

export function Field({
  label,
  hint,
  error,
  revealable = false,
  required,
  type = "text",
  inputClassName,
  inputRef,
  ...rest
}: FieldProps): JSX.Element {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const [revealed, setRevealed] = useState(false);

  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  const inputType = revealable && revealed ? "text" : type;
  const classes = ["sunil-field__input", "sunil-type-body"];
  if (inputClassName) classes.push(inputClassName);

  return (
    <div className="sunil-field">
      <label className="sunil-field__label sunil-type-micro" htmlFor={id}>
        {label}
        {required ? " (Required)" : null}
      </label>
      <div className="sunil-field__control">
        <input
          {...rest}
          ref={inputRef}
          id={id}
          type={inputType}
          className={classes.join(" ")}
          required={required}
          aria-required={required ? true : undefined}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy === "" ? undefined : describedBy}
        />
        {revealable ? (
          <button
            type="button"
            className="sunil-field__adornment"
            aria-pressed={revealed}
            aria-label={revealed ? "Hide password" : "Show password"}
            onClick={() => {
              setRevealed((value) => !value);
            }}
          >
            <span aria-hidden="true" className="sunil-type-micro">
              {revealed ? "HIDE" : "SHOW"}
            </span>
          </button>
        ) : null}
      </div>
      {hint ? (
        <p className="sunil-field__hint sunil-type-caption" id={hintId}>
          {hint}
        </p>
      ) : null}
      {error ? (
        <p className="sunil-field__error sunil-type-caption" id={errorId}>
          {error}
        </p>
      ) : null}
    </div>
  );
}
