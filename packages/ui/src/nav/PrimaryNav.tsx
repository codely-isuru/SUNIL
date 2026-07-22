/**
 * The primary navigation — PORTAL_SHELL_SPEC.md §5.
 *
 * §5.4 is the decision this component exists to make visible, and it is deliberately
 * counter-intuitive, so it is restated here where it is implemented:
 *
 *   An unavailable destination is a `<span>` inside an `<li>`. NOT an `<a href="#">` (that is
 *   a broken page with extra steps — FR-101), NOT a `<button disabled>` (removed from the tab
 *   order AND commonly skipped by AT heuristics, so the item would vanish for some users), and
 *   NOT `aria-disabled` (meaningless on a non-interactive element). It carries no `tabindex`,
 *   so keyboard users tab through the destinations that exist instead of 19 dead stops, and it
 *   carries an `.sr-only` "— not yet available" so browsing the list still reads the truth.
 *
 * Opacity is applied to the ICON only; applying it to the label would silently change the
 * label's measured contrast, which is the exact class of bug the token audit exists to prevent.
 */
import type { JSX, ReactNode, Ref } from "react";
import type { NavGroup } from "./destinations.js";
import { NavIcon } from "./icons.js";

export interface PrimaryNavProps {
  groups: readonly NavGroup[];
  /** The current pathname, used for `aria-current="page"`. */
  currentPath: string;
  /** Rendered above the list: brand block. */
  brand?: ReactNode;
  /** Rendered below the list: user chip, sign out, and on xs/sm the clock and status pill. */
  footer?: ReactNode;
  /** Set when the permission set could not be loaded (§13 error state). */
  limited?: boolean;
  id?: string;
  className?: string;
  onNavigate?: () => void;
  /** The shell attaches its drawer focus-trap to the <nav> element itself. */
  navRef?: Ref<HTMLElement>;
}

function isCurrent(href: string, currentPath: string): boolean {
  if (href === "/") return currentPath === "/";
  return currentPath === href || currentPath.startsWith(`${href}/`);
}

export function PrimaryNav({
  groups,
  currentPath,
  brand,
  footer,
  limited = false,
  id = "primary-nav",
  className,
  onNavigate,
  navRef,
}: PrimaryNavProps): JSX.Element {
  return (
    <nav
      ref={navRef}
      id={id}
      aria-label="Primary"
      className={className ? `sunil-shell__nav ${className}` : "sunil-shell__nav"}
    >
      {brand}
      <div className="sunil-nav__scroll">
        {limited ? (
          <p className="sunil-nav__group-label sunil-type-micro">
            Navigation limited — permissions unavailable
          </p>
        ) : null}
        {groups.map((group) => (
          <div className="sunil-nav__group" key={group.id}>
            <h2 className="sunil-nav__group-label sunil-type-micro">{group.label}</h2>
            <ul>
              {group.items.map((item) =>
                item.href === undefined ? (
                  <li
                    key={item.id}
                    className="sunil-nav__item sunil-nav__item--unavailable sunil-type-body-sm"
                  >
                    <NavIcon name={item.icon} />
                    <span className="sunil-nav__label">{item.label}</span>
                    {item.badge ? (
                      <span className="sunil-badge sunil-type-micro">{item.badge}</span>
                    ) : null}
                    <span className="sunil-sr-only">— not yet available</span>
                  </li>
                ) : (
                  <li key={item.id}>
                    <a
                      className="sunil-nav__item sunil-type-body-sm"
                      href={item.href}
                      aria-current={isCurrent(item.href, currentPath) ? "page" : undefined}
                      onClick={onNavigate}
                    >
                      <NavIcon name={item.icon} />
                      <span className="sunil-nav__label">{item.label}</span>
                      {item.badge ? (
                        <span className="sunil-badge sunil-type-micro">{item.badge}</span>
                      ) : null}
                    </a>
                  </li>
                ),
              )}
            </ul>
          </div>
        ))}
      </div>
      {footer}
    </nav>
  );
}
