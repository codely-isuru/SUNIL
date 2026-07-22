/**
 * The four-state gallery — PORTAL_SHELL_SPEC.md §13 and the §14 checklist item
 * "every component in §13 demonstrably reaches all four states (storybook, fixture or dev
 * route)". This is that dev route.
 *
 * It is NOT part of the product: it returns 404 in a production build, so it cannot become a
 * page a user reaches, and nothing it renders is wired to an API. Every value on it is a
 * fixture, and it says so on the page — a gallery of fake states is exactly the kind of screen
 * NFR-019 exists to stop being mistaken for real.
 */
import { notFound } from "next/navigation";
import type { JSX } from "react";
import type { Metadata } from "next";
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  Lamp,
  NAV_GROUPS,
  Panel,
  PresenceFallback,
  PrimaryNav,
  Skeleton,
  StatTile,
  SunilPresence,
  visibleGroups,
} from "@sunil/ui";

export const metadata: Metadata = { title: "Component states (dev)" };

const STATES = ["Empty", "Loading", "Success", "Error"] as const;

function Row({ title, children }: { title: string; children: JSX.Element[] }): JSX.Element {
  return (
    <Panel title={title} titleId={`states-${title.replace(/\W+/g, "-").toLowerCase()}`}>
      <div className="sunil-card-grid">
        {children.map((child, index) => (
          <div className="sunil-card" key={STATES[index]}>
            <span className="sunil-card__title sunil-type-eyebrow">{STATES[index]}</span>
            {child}
          </div>
        ))}
      </div>
    </Panel>
  );
}

export default function ComponentStatesPage(): JSX.Element {
  if (process.env.NODE_ENV === "production") notFound();

  return (
    <main id="main" className="sunil-main sunil-shell__main" tabIndex={-1}>
      <div className="sunil-shell__content">
        <h1 className="sunil-type-title">Component states</h1>
        <Alert tone="info">
          Development route. Every value below is a FIXTURE, not live data, and this page is not
          reachable in a production build.
        </Alert>

        <Row title="Button">
          <span className="sunil-type-caption">Not applicable — a button has no empty state.</span>
          <Button busy busyLabel="Authenticating">
            Access
          </Button>
          <Button>Access</Button>
          <span className="sunil-type-caption">
            Returns to rest; the error appears in the alert region, never inside the button.
          </span>
        </Row>

        <Row title="Field">
          <span className="sunil-type-caption">
            Placeholder is a format example only, never the label.
          </span>
          <Skeleton height={44} />
          <span className="sunil-type-caption">Border returns to the interactive token.</span>
          <span className="sunil-field__error sunil-type-caption">
            aria-invalid, error border, message below via aria-describedby.
          </span>
        </Row>

        <Row title="Panel">
          <EmptyState>No recovery codes generated.</EmptyState>
          <Skeleton height={72} />
          <span className="sunil-type-caption">Content.</span>
          <Alert>Inline alert inside the panel; the panel keeps its frame and title.</Alert>
        </Row>

        <Row title="Lamp and status">
          <span className="sunil-type-caption">Unreachable — a lamp always has a state.</span>
          <span className="sunil-list__row">
            <Lamp state="unknown" label="Checking" />
            <span className="sunil-type-micro">CHECKING</span>
          </span>
          <span className="sunil-list__row">
            <Lamp state="on" label="Nominal" />
            <span className="sunil-type-micro">NOMINAL</span>
          </span>
          <span className="sunil-list__row">
            <Lamp state="off" label="No signal" />
            <span className="sunil-type-micro">NO SIGNAL</span>
          </span>
        </Row>

        <Row title="Queue figures">
          <StatTile label="Completed" value={0} />
          <Skeleton height={64} />
          <StatTile label="Waiting" value={12} />
          <StatTile label="Failed" value={3} tone="danger" />
        </Row>

        <Panel title="Presence — the three states plus the fallback" titleId="states-presence">
          <div className="sunil-card-grid">
            <div className="sunil-card">
              <span className="sunil-card__title sunil-type-eyebrow">Idle</span>
              <SunilPresence state="idle" size={200} announce={false} />
            </div>
            <div className="sunil-card">
              <span className="sunil-card__title sunil-type-eyebrow">Thinking</span>
              <SunilPresence state="thinking" size={200} announce={false} />
            </div>
            <div className="sunil-card">
              <span className="sunil-card__title sunil-type-eyebrow">Speaking</span>
              <SunilPresence state="speaking" size={200} announce={false} />
            </div>
            <div className="sunil-card">
              <span className="sunil-card__title sunil-type-eyebrow">Canvas unavailable</span>
              <PresenceFallback />
            </div>
          </div>
        </Panel>

        <Panel title="Navigation" titleId="states-nav">
          <p className="sunil-type-caption">
            22 destinations. Three are links; nineteen are non-focusable badged spans with a
            phase marker. <Badge>Phase 2</Badge>
          </p>
          <PrimaryNav
            groups={visibleGroups(NAV_GROUPS, ["settings:read"])}
            currentPath="/"
            id="dev-nav"
          />
        </Panel>
      </div>
    </main>
  );
}
