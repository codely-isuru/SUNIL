"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Icon, type IconName } from "@/components/ui/Icon";
import { useShellData } from "./ShellData";

/**
 * The labelled icon rail (§1.2). 88px, and **every item shows its label** —
 * hover-only labels fail `nav-label-icon` and are unreachable on touch, which
 * is why the mockups' rail is 88px rather than a 56px icon strip.
 *
 * Active item: 2px gold left bar + `surface-raised` ground + `text-secondary`
 * label + `aria-current="page"`. No glow at rest (§A.4 — glow is a state).
 *
 * Under 768px this becomes the five-item bottom bar (§1.4), Home / Chat /
 * Approve / Activity / More, honouring `bottom-nav-limit`.
 */

interface NavItem {
  href: string;
  icon: IconName;
  label: string;
  longLabel: string;
  /** Match sub-routes (`/approvals/{id}`) as the same destination. */
  prefix?: boolean;
  badge?: "pending";
  inBottomBar?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { href: "/", icon: "dashboard", label: "Home", longLabel: "Dashboard", inBottomBar: true },
  { href: "/chat", icon: "chat", label: "Chat", longLabel: "Chat", prefix: true, inBottomBar: true },
  {
    href: "/approvals",
    icon: "shield-check",
    label: "Approve",
    longLabel: "Approvals",
    prefix: true,
    badge: "pending",
    inBottomBar: true,
  },
  { href: "/activity", icon: "activity", label: "Activity", longLabel: "Activity", inBottomBar: true },
  { href: "/tasks", icon: "list-checks", label: "Tasks", longLabel: "Tasks", prefix: true },
  { href: "/projects", icon: "folder", label: "Projects", longLabel: "Projects", prefix: true },
  { href: "/audit", icon: "file-search", label: "Audit", longLabel: "Audit", prefix: true },
];

function isActive(pathname: string, item: NavItem) {
  if (item.href === "/") return pathname === "/";
  return item.prefix ? pathname === item.href || pathname.startsWith(`${item.href}/`) : pathname === item.href;
}

const ITEM_BASE =
  "relative flex w-[76px] min-h-[56px] flex-col items-center gap-[5px] rounded-md border-l-2 border-transparent px-0.5 py-2 text-text-muted hover:bg-surface-raised hover:text-text-secondary md:w-[58px] xl:w-[76px]";

export function NavRail() {
  const pathname = usePathname() ?? "/";
  const { pendingCount } = useShellData();

  return (
    <nav
      aria-label="Primary"
      className="sticky top-0 hidden h-dvh flex-col items-center border-r border-border bg-surface pb-4 pt-3 md:flex"
    >
      <div className="px-0 pb-4 pt-1.5 font-display text-[0.8125rem] font-bold tracking-brand text-accent">
        S
      </div>

      <div className="flex w-full flex-col items-center gap-0.5">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={`${ITEM_BASE} ${
                active ? "border-l-accent bg-surface-raised text-text-secondary" : ""
              }`}
            >
              <Icon name={item.icon} />
              <span className="text-micro font-semibold uppercase tracking-[0.08em]">
                {item.label}
              </span>
              {item.badge === "pending" && pendingCount > 0 ? (
                <>
                  <span
                    aria-hidden="true"
                    className="absolute right-2.5 top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-status-pending px-[5px] font-mono text-micro font-semibold text-accent-on"
                  >
                    {pendingCount > 99 ? "99+" : pendingCount}
                  </span>
                  <span className="sr-only">{`Approvals, ${pendingCount} pending`}</span>
                </>
              ) : null}
            </Link>
          );
        })}
      </div>

      {/* Spacer — pushes Settings/Sign out to the bottom so a destructive
          action never sits flush against navigation (§1.2). */}
      <div className="flex-1" />

      <Link href="/settings" className={ITEM_BASE}>
        <Icon name="settings" />
        <span className="text-micro font-semibold uppercase tracking-[0.08em]">Settings</span>
      </Link>
      <button
        type="button"
        className={`${ITEM_BASE} hover:text-danger`}
        onClick={() => {
          // Sign-out is an action, not a route (§1.2). Wired to the C-auth
          // endpoint at integration; the mock session has nothing to end.
          window.alert("Sign out is wired to POST /api/v1/auth/logout at integration.");
        }}
      >
        <Icon name="log-out" />
        <span className="text-micro font-semibold uppercase tracking-[0.08em]">Sign out</span>
      </button>
    </nav>
  );
}

/** §1.4 — under 768px: five items, labels always visible. */
export function NavBottomBar() {
  const pathname = usePathname() ?? "/";
  const { pendingCount } = useShellData();
  const items = NAV_ITEMS.filter((i) => i.inBottomBar);

  return (
    <nav
      aria-label="Primary"
      className="fixed bottom-0 left-0 right-0 z-20 grid grid-cols-5 border-t border-border bg-surface pb-[env(safe-area-inset-bottom)] md:hidden"
    >
      {items.map((item) => {
        const active = isActive(pathname, item);
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={`relative flex min-h-[56px] flex-col items-center justify-center gap-1 text-micro font-semibold uppercase tracking-[0.08em] ${
              active ? "text-text-secondary" : "text-text-muted"
            }`}
          >
            <Icon name={item.icon} size={18} />
            {item.label}
            {item.badge === "pending" && pendingCount > 0 ? (
              <>
                <span
                  aria-hidden="true"
                  className="absolute right-3.5 top-1 flex h-[18px] min-w-[18px] items-center justify-center rounded-full bg-status-pending px-[5px] font-mono text-micro font-semibold text-accent-on"
                >
                  {pendingCount > 99 ? "99+" : pendingCount}
                </span>
                <span className="sr-only">{`Approvals, ${pendingCount} pending`}</span>
              </>
            ) : null}
          </Link>
        );
      })}
      <Link
        href="/tasks"
        className="flex min-h-[56px] flex-col items-center justify-center gap-1 text-micro font-semibold uppercase tracking-[0.08em] text-text-muted"
      >
        <Icon name="rows" size={18} />
        More
      </Link>
    </nav>
  );
}
