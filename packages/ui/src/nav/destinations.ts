/**
 * The information architecture — all 22 destinations, PORTAL_SHELL_SPEC.md §5.1.
 *
 * Gate 1 (Q10) decided the full navigation is shown, so this list is the product's shape as
 * the owner will see it on day one. Four destinations work. Eighteen do not, and each carries
 * the phase it arrives in, taken from the §1.3 exclusion table of PHASE1_REQUIREMENTS.md —
 * not invented, and where that table gives a range the LATER phase is shown, because
 * over-promising is the failure mode the marker exists to prevent.
 *
 * `permission` is presentation only. Hiding is never the control: the API enforces
 * independently (ET-2 step 2.6), and nothing in this file may suggest otherwise.
 */
import type { IconName } from "./icons.js";

export interface NavDestination {
  readonly id: string;
  readonly label: string;
  readonly icon: IconName;
  /** Present only for the four destinations that actually exist in Phase 1. */
  readonly href?: string;
  /** The phase badge shown on an unavailable destination, or `MINIMAL` for Settings. */
  readonly badge?: string;
  /** When set, the item is hidden unless the session carries this permission (FR-101). */
  readonly permission?: string;
}

export interface NavGroup {
  readonly id: string;
  readonly label: string;
  readonly items: readonly NavDestination[];
}

export const NAV_GROUPS: readonly NavGroup[] = [
  {
    id: "overview",
    label: "Overview",
    items: [
      { id: "dashboard", label: "Dashboard", icon: "dashboard", href: "/" },
      { id: "chat", label: "SUNIL Chat", icon: "chat", badge: "Phase 2" },
      { id: "brief", label: "Daily Brief", icon: "brief", badge: "Phase 3" },
    ],
  },
  {
    id: "work",
    label: "Work",
    items: [
      { id: "tasks", label: "Tasks", icon: "tasks", badge: "Phase 2" },
      { id: "calendar", label: "Calendar", icon: "calendar", badge: "Phase 3" },
      { id: "emails", label: "Emails", icon: "mail", badge: "Phase 3" },
      { id: "support", label: "Support", icon: "support", badge: "Phase 4" },
      { id: "jira", label: "Jira", icon: "board", badge: "Phase 4" },
      { id: "teams", label: "Teams", icon: "teams", badge: "Phase 4" },
    ],
  },
  {
    id: "intelligence",
    label: "Intelligence",
    items: [
      { id: "agents", label: "Agents", icon: "agents", badge: "Phase 2" },
      { id: "ai-teams", label: "AI Teams", icon: "aiTeams", badge: "Phase 5" },
      { id: "workflows", label: "Workflows", icon: "workflows", badge: "Phase 3" },
      { id: "memory", label: "Memory", icon: "memory", badge: "Phase 2" },
    ],
  },
  {
    id: "governance",
    label: "Governance",
    items: [
      { id: "approvals", label: "Approvals", icon: "approvals", badge: "Phase 2" },
      { id: "notifications", label: "Notifications", icon: "bell", badge: "Phase 2" },
      { id: "activity", label: "Activity Logs", icon: "logs", badge: "Phase 2" },
    ],
  },
  {
    id: "platform",
    label: "Platform",
    items: [
      { id: "integrations", label: "Integrations", icon: "integrations", badge: "Phase 3" },
      { id: "providers", label: "LLM Providers", icon: "providers", badge: "Phase 2" },
      { id: "routing", label: "Model Routing", icon: "routing", badge: "Phase 2" },
      { id: "usage", label: "Usage", icon: "usage", badge: "Phase 2" },
      {
        id: "settings",
        label: "Settings",
        icon: "settings",
        href: "/settings",
        badge: "Minimal",
        permission: "settings:read",
      },
      { id: "health", label: "System Health", icon: "health", href: "/system-health" },
    ],
  },
];

/**
 * The destinations that are real in Phase 1. Anything else must not have an `href` —
 * FR-101: "none linking to a broken page", and an `<a href="#">` is a broken page with extra
 * steps (§5.4).
 *
 * NOTE FOR THE DESIGNER: §5.1's table marks exactly THREE nav destinations live (Dashboard,
 * Settings, System Health), while the §14 handover checklist says "exactly 4 are links; 18 are
 * non-focusable badged spans". §5.1 is implemented, because §1's fourth functional destination
 * is sign-in, which is not a nav item. 22 = 3 links + 19 spans.
 */
export const PHASE_1_ROUTES: readonly string[] = ["/", "/settings", "/system-health"];

/** Total destination count, asserted by a test so the list cannot silently shrink (Q10). */
export const NAV_DESTINATION_COUNT = NAV_GROUPS.reduce(
  (total, group) => total + group.items.length,
  0,
);

/**
 * Apply permission filtering. An item the user lacks permission for is HIDDEN, not disabled:
 * "disabled" means *not built yet*, "hidden" means *not yours*, and conflating them would tell
 * a viewer that Settings is coming in a later phase (§5.5). A group whose every item is hidden
 * disappears with them.
 */
export function visibleGroups(
  groups: readonly NavGroup[],
  permissions: readonly string[],
): NavGroup[] {
  const granted = new Set(permissions);
  const result: NavGroup[] = [];
  for (const group of groups) {
    const items = group.items.filter(
      (item) => item.permission === undefined || granted.has(item.permission),
    );
    if (items.length > 0) result.push({ ...group, items });
  }
  return result;
}

/**
 * The §13 error state for the nav: when the permission set cannot be loaded, render the Phase 1
 * destinations that need no permission and NOTHING else. Never render everything as a fallback
 * — a nav that fails open is a nav that lies about what the user may do.
 */
export function limitedGroups(groups: readonly NavGroup[]): NavGroup[] {
  const result: NavGroup[] = [];
  for (const group of groups) {
    const items = group.items.filter(
      (item) => item.href !== undefined && item.permission === undefined,
    );
    if (items.length > 0) result.push({ ...group, items });
  }
  return result;
}
