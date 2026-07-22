/**
 * The authenticated shell layout — PORTAL_SHELL_SPEC.md §3, §5.5, §6.7, §13.
 *
 * A SERVER component: it forwards the incoming session cookie to `GET /api/auth/me` (§14) so
 * no protected content is ever assembled in the browser from a token the browser holds. The
 * permission array it returns drives which nav items are VISIBLE — and hiding is never the
 * control (ET-2 2.6): every route the nav points at is enforced by the API independently.
 *
 * `apps/api` does not exist yet, so in practice this call currently fails, and that is why the
 * §13 error state is built rather than assumed: the shell renders the unguarded Phase 1
 * destinations only, marks itself "Navigation limited", and announces it. It never falls open
 * to the full list — a nav that fails open lies about what the user may do.
 */
import type { JSX, ReactNode } from "react";
import { cookies } from "next/headers";
import { NAV_GROUPS, limitedGroups, resolveTimeZone, visibleGroups } from "@sunil/ui";
import type { NavGroup } from "@sunil/ui";
import { AppShell } from "../../components/AppShell";
import { TimeZoneProvider } from "../../lib/time/TimeZoneProvider";
import { SessionProvider } from "../../lib/session/SessionProvider";
import { AppearanceProvider } from "../../lib/appearance/AppearanceProvider";
import { fetchMe } from "../../lib/api/client";

// The session cookie makes every authenticated page request-scoped; nothing here may be
// statically rendered at build time.
export const dynamic = "force-dynamic";

export default async function PortalLayout({
  children,
}: {
  children: ReactNode;
}): Promise<JSX.Element> {
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((entry) => `${entry.name}=${entry.value}`)
    .join("; ");

  const me = await fetchMe(cookieHeader === "" ? undefined : cookieHeader);

  let groups: readonly NavGroup[];
  let displayName = "Signed-in user";
  let roleLabel = "Role unavailable";
  let timeZone = resolveTimeZone();
  let csrfToken: string | undefined;
  const limited = !me.ok;

  if (me.ok) {
    groups = visibleGroups(NAV_GROUPS, me.data.permissions);
    displayName = me.data.user.displayName;
    roleLabel = me.data.roles.map((role) => role.name).join(", ") || "No role";
    timeZone = resolveTimeZone({ user: me.data.user.timezone });
    csrfToken = me.data.csrfToken;
  } else {
    groups = limitedGroups(NAV_GROUPS);
  }

  return (
    <SessionProvider
      value={{
        displayName,
        roleLabel,
        permissions: me.ok ? me.data.permissions : [],
        ...(csrfToken === undefined ? {} : { csrfToken }),
        limited,
      }}
    >
      <TimeZoneProvider initialTimeZone={timeZone}>
        <AppearanceProvider>
        <AppShell
          groups={groups}
          displayName={displayName}
          roleLabel={roleLabel}
          csrfToken={csrfToken}
          limited={limited}
        >
          {children}
        </AppShell>
        </AppearanceProvider>
      </TimeZoneProvider>
    </SessionProvider>
  );
}
