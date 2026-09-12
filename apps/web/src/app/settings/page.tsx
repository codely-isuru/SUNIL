"use client";

import { useEffect, useState } from "react";
import { AppShell } from "@/components/shell/AppShell";
import { Button, Panel, SectionHeading, ViewHeading, ViewSubhead } from "@/components/ui/primitives";
import { API_BASE_URL, dataSource, setDataSource, type DataSource } from "@/lib/api";

/**
 * Settings (`/settings`) — a stub in the spec (§1.2), listed so the rail's
 * final shape is not a surprise later. It carries exactly one real control
 * for now: **the data-source flag**, which is how this app flips from the
 * standalone mock world to the FastAPI base URL at integration.
 */
export default function SettingsPage() {
  return (
    <AppShell title="Settings" crumbs={[{ label: "Settings" }]}>
      <SettingsView />
    </AppShell>
  );
}

function SettingsView() {
  const [source, setSource] = useState<DataSource>("mock");

  // The flag lives in localStorage, which does not exist during the server
  // render — reading it after hydration is the only correct order, and the
  // state flip is the point.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setSource(dataSource());
  }, []);

  function choose(next: DataSource) {
    setDataSource(next);
    setSource(next);
    window.location.reload();
  }

  return (
    <>
      <ViewHeading>Settings</ViewHeading>
      <ViewSubhead>
        Not designed yet (spec §1.2 lists it as a stub). The data-source switch below is a build
        affordance, not a product feature.
      </ViewSubhead>

      <Panel className="mt-4 p-5">
        <SectionHeading>Data source</SectionHeading>
        <p className="mt-2 text-cell text-text-muted">
          {`Currently `}
          <b className="text-text-secondary">{source === "mock" ? "mock fixtures" : "the live API"}</b>
          {source === "mock"
            ? " — the app serves the OpenAPI shapes from the same Codely fixture world as the approved mockups, with no FastAPI process running."
            : ` — every read and the decision POST go to ${API_BASE_URL} with credentials: "include" and X-SUNIL-Client: web (ADR-008).`}
        </p>
        <div className="mt-3.5 flex gap-3">
          <Button variant={source === "mock" ? "primary" : "ghost"} onClick={() => choose("mock")}>
            Mock fixtures
          </Button>
          <Button variant={source === "api" ? "primary" : "ghost"} onClick={() => choose("api")}>
            Live API
          </Button>
        </div>
        <p className="mt-3 text-small text-text-muted">
          {`The default also comes from NEXT_PUBLIC_SUNIL_DATA_SOURCE; the base URL from
          NEXT_PUBLIC_API_BASE_URL (dev must be http://localhost:8000, never 127.0.0.1 — a host
          mismatch silently withholds the SameSite=Lax session cookie).`}
        </p>
      </Panel>
    </>
  );
}
