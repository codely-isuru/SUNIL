/**
 * Panel — the prototype's `.panel`, with its 46px accent bar and 12px inset intact.
 *
 * `opaque` is not a style choice. Anything sitting over the presence canvas MUST use it:
 * a translucent surface over an animated backdrop has an unmeasurable text contrast ratio
 * (DESIGN_TOKENS.md §5.4.3).
 *
 * Headings: the page `<h1>` is the header page title, so a panel title is an `<h2>` and
 * content inside a panel starts at `<h3>` (PORTAL_SHELL_SPEC.md §3).
 */
import type { JSX, ReactNode } from "react";

export function Panel({
  title,
  titleId,
  opaque = false,
  headerAction,
  children,
  busy,
  className,
}: {
  title?: string;
  titleId?: string;
  opaque?: boolean;
  headerAction?: ReactNode;
  children: ReactNode;
  busy?: boolean;
  className?: string;
}): JSX.Element {
  const classes = ["sunil-panel"];
  if (opaque) classes.push("sunil-panel--opaque");
  if (className) classes.push(className);

  return (
    <section
      className={classes.join(" ")}
      aria-labelledby={title ? titleId : undefined}
      aria-busy={busy ? true : undefined}
    >
      {title ? (
        <h2 className="sunil-panel__title sunil-type-eyebrow" id={titleId}>
          {title}
        </h2>
      ) : null}
      {headerAction}
      {children}
    </section>
  );
}
