/**
 * The dashboard — PORTAL_SHELL_SPEC.md §8. "An honest empty foundation."
 *
 * WHAT IS DELIBERATELY ABSENT (§8.7, A-09, NFR-019, architectural rule 7): the prototype's MRR
 * / subscriber / ad-spend / ticket tiles, its content queue, its priority task list, its
 * Gmail / RevenueCat / Metricool / Meta Ads connector lamps, its "Brief Me" button, and every
 * chart. All of that is hard-coded in `window.SUNIL_DATA`. Copying the layout and filling it
 * with placeholders would produce a screen that lies at a glance.
 *
 * What is here instead: the prototype's spatial language — centre stage, flanking panels, a
 * bottom row — with the empty regions genuinely empty, one panel of real data, and a permanent
 * banner that says what phase this is. Every number on this page comes from
 * `GET /api/system-health` or does not exist.
 */
import type { JSX } from "react";
import type { Metadata } from "next";
import { Badge, NAV_GROUPS, Panel } from "@sunil/ui";
import { PresenceBlock } from "../../components/PresenceBlock";
import { PlatformStatusPanel } from "../../components/PlatformStatusPanel";

export const metadata: Metadata = { title: "Dashboard" };

/**
 * The "not yet available" list uses the SAME vocabulary as the navigation, so nothing has to
 * be learned twice (§8.5). It is derived from the nav model rather than retyped, which is why
 * it cannot drift from the badges in the sidebar.
 */
const UPCOMING = NAV_GROUPS.flatMap((group) =>
  group.items
    .filter((item) => item.href === undefined)
    .map((item) => ({ id: item.id, label: item.label, badge: item.badge ?? "Later" })),
);

const NEXT_CARDS = [
  {
    href: "/settings",
    title: "Settings",
    body: "Your profile, time zone, security and appearance. Minimal in Phase 1.",
  },
  {
    href: "/system-health",
    title: "System Health",
    body: "Live dependency, queue and provider status from the API.",
  },
  {
    href: "/settings",
    title: "Sessions & sign-out",
    body: "Review active sessions and revoke the ones you do not recognise.",
  },
];

export default function DashboardPage(): JSX.Element {
  return (
    <>
      {/* Permanent and not dismissible: a banner the user can hide is a banner that stops
          being true (§8.2). */}
      <section className="sunil-phase-banner sunil-type-body">
        <strong>Phase 1 — Foundation.</strong> SUNIL is installed and secured, but has no
        assistant features yet. Sign-in, settings and system health work. Everything else in the
        navigation arrives in a later phase. <strong>No business data is connected.</strong>
      </section>

      <div className="sunil-dash">
        <div className="sunil-dash__status">
          <PlatformStatusPanel />
        </div>

        <div className="sunil-dash__presence">
          <PresenceBlock />
        </div>

        <div className="sunil-dash__soon">
          <Panel title="Not yet available" titleId="not-yet-available-title">
            <ul className="sunil-list">
              {UPCOMING.map((item) => (
                <li className="sunil-list__row sunil-type-caption" key={item.id}>
                  <span className="sunil-list__row-label">{item.label}</span>
                  <Badge>{item.badge}</Badge>
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <div className="sunil-dash__next">
          <h2 className="sunil-type-eyebrow sunil-fg-heading">Where to go next</h2>
          <div className="sunil-card-grid">
            {NEXT_CARDS.map((card) => (
              <a className="sunil-card" href={card.href} key={card.title}>
                <span className="sunil-card__title sunil-type-eyebrow">{card.title}</span>
                <span className="sunil-type-caption">{card.body}</span>
              </a>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
