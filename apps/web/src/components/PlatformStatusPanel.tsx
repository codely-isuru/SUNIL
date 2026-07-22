"use client";

/**
 * The dashboard's ONLY live-data panel — PORTAL_SHELL_SPEC.md §8.4.
 *
 * ───────────────────────────────────────────────────────────────────────────────────────────
 * A CONTRACT GAP, HANDLED HONESTLY RATHER THAN FILLED IN.
 *
 * §8.4 asks for six rows: DATABASE, REDIS, API, WORKER, SCHEDULER, PGVECTOR.
 * PHASE1_ARCHITECTURE §13 defines `GET /system-health` as returning
 * `{status, deps: {postgres: 'up'|'down', redis: 'up'|'down'}}` — two dependencies, "booleans
 * only, no versions/connection detail (FR-091)".
 *
 * So four of the six rows have no source. They are rendered in the UNKNOWN state with the
 * words `NOT REPORTED`, never as green, never as a guess, and never omitted — a vanished row
 * reads as "fine", which is the opposite of the truth (§10.3). If the API later reports them,
 * they light up with no change here: the row set is derived from the response plus a fixed
 * list, and anything the response does not mention is unknown by construction.
 * ───────────────────────────────────────────────────────────────────────────────────────────
 */
import type { JSX } from "react";
import { Alert, Lamp, Panel, Skeleton } from "@sunil/ui";
import { useSystemHealth } from "../lib/api/useSystemHealth";
import type { DependencyState } from "../lib/api/types";

/** Display name → the key §13's `deps` map uses, where one exists. */
const ROWS: readonly { label: string; depKey: string | null }[] = [
  { label: "DATABASE", depKey: "postgres" },
  { label: "REDIS", depKey: "redis" },
  { label: "API", depKey: "api" },
  { label: "WORKER", depKey: "worker" },
  { label: "SCHEDULER", depKey: "scheduler" },
  { label: "PGVECTOR", depKey: "pgvector" },
];

const POLL_MS = 30_000;

function rowPresentation(
  value: DependencyState | undefined,
  failed: boolean,
): { lamp: "on" | "error" | "off" | "unknown"; state: string } {
  if (failed) return { lamp: "off", state: "NO SIGNAL" };
  if (value === "up") return { lamp: "on", state: "ONLINE" };
  if (value === "down") return { lamp: "error", state: "DOWN" };
  return { lamp: "unknown", state: "NOT REPORTED" };
}

export function PlatformStatusPanel(): JSX.Element {
  const health = useSystemHealth(POLL_MS);
  const failed = health.phase === "error";
  const loading = health.phase === "loading";

  return (
    <Panel title="Platform status" titleId="platform-status-title" busy={loading}>
      {loading ? (
        <>
          <span className="sunil-sr-only">Loading platform status</span>
          <div className="sunil-list">
            {ROWS.map((row) => (
              // Skeletons at the FINAL row dimensions, so nothing shifts when data lands.
              <Skeleton key={row.label} height={30} />
            ))}
          </div>
        </>
      ) : (
        <div className="sunil-list">
          {ROWS.map((row) => {
            const value = row.depKey === null ? undefined : health.data?.deps[row.depKey];
            const { lamp, state } = rowPresentation(value, failed);
            return (
              <div className="sunil-sysrow" key={row.label}>
                <Lamp state={lamp} label={`${row.label}: ${state}`} />
                <span className="sunil-sysrow__name sunil-type-caption" aria-hidden="true">
                  {row.label}
                </span>
                <span className="sunil-sysrow__state sunil-type-micro" aria-hidden="true">
                  {state}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {failed ? <Alert>Could not reach the health endpoint.</Alert> : null}

      <p className="sunil-type-caption">
        <a href="/system-health">Full system health →</a>
      </p>
    </Panel>
  );
}
