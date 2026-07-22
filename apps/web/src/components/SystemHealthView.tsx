"use client";

/**
 * System Health — PORTAL_SHELL_SPEC.md §10. Real data, real refresh, no fabrication.
 *
 * Constraints that are as much UI constraints as API ones:
 *   - NO version strings, connection strings or host names on screen. FR-091 forbids exposing
 *     detail that aids an attacker, and a dependency card is exactly where that leaks.
 *   - `FAILED` renders in the danger colour only when it is greater than zero. A red zero is a
 *     false alarm, and false alarms are how real ones get ignored.
 *   - LLM providers are NEVER green and never say ONLINE or HEALTHY, under any circumstance
 *     (FR-065): no adapter has been verified against a live endpoint in Phase 1.
 *   - Auto-refresh pauses when the tab is hidden, backs off on failure, and defaults to OFF
 *     under `prefers-reduced-motion` — content that changes under you without warning is a
 *     motion problem as much as an animation is (§10.2, §11.6).
 *   - A refresh NEVER moves focus and never reorders cards. In-place value updates only.
 */
import { useEffect, useRef, useState } from "react";
import type { JSX } from "react";
import {
  Alert,
  Button,
  EmptyState,
  Lamp,
  Panel,
  Skeleton,
  StatTile,
  formatRelativeTime,
  isoWithOffset,
} from "@sunil/ui";
import { statusPresentation, useSystemHealth } from "../lib/api/useSystemHealth";
import { fetchJobsStatus, fetchProviders } from "../lib/api/client";
import type { ApiFailureKind, JobsStatusResponse, ProviderSummary } from "../lib/api/types";
import { useTimeZone } from "../lib/time/TimeZoneProvider";

const REFRESH_MS = 15_000;

const DEPENDENCIES: readonly { label: string; depKey: string | null; detail: string }[] = [
  { label: "DATABASE", depKey: "postgres", detail: "Primary datastore." },
  { label: "REDIS", depKey: "redis", detail: "Queue and rate-limit store." },
  {
    label: "PGVECTOR EXTENSION",
    depKey: "pgvector",
    detail: "Vector extension. Not reported by the Phase 1 health endpoint.",
  },
  { label: "API", depKey: "api", detail: "Answering this request." },
  {
    label: "WORKER",
    depKey: "worker",
    detail: "Job processor. Not reported by the Phase 1 health endpoint.",
  },
  {
    label: "SCHEDULER",
    depKey: "scheduler",
    detail: "Repeatable jobs. Not reported by the Phase 1 health endpoint.",
  },
];

function providerLabel(provider: ProviderSummary): string {
  // FR-065 / §10.5. Even a MOCK_VERIFIED adapter is unverified against a live endpoint.
  if (provider.credentialName === null) return "NOT CONFIGURED · UNVERIFIED";
  if (provider.verification === "LIVE_VERIFIED") return "CONFIGURED · LIVE-VERIFIED";
  return "CONFIGURED · UNVERIFIED";
}

export function SystemHealthView(): JSX.Element {
  const { timeZone } = useTimeZone();
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [reducedMotion, setReducedMotion] = useState(false);
  const [now, setNow] = useState<Date | null>(null);

  const [jobs, setJobs] = useState<JobsStatusResponse | null>(null);
  const [jobsError, setJobsError] = useState<ApiFailureKind | null>(null);
  const [providers, setProviders] = useState<readonly ProviderSummary[] | null>(null);
  const [providersError, setProvidersError] = useState<ApiFailureKind | null>(null);
  const initialisedRef = useRef(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return undefined;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const apply = (matches: boolean): void => {
      setReducedMotion(matches);
      if (!initialisedRef.current) {
        // Default OFF under reduced motion; the manual REFRESH button is always present.
        setAutoRefresh(!matches);
        initialisedRef.current = true;
      }
    };
    apply(query.matches);
    const onChange = (event: MediaQueryListEvent): void => {
      apply(event.matches);
    };
    query.addEventListener("change", onChange);
    return () => {
      query.removeEventListener("change", onChange);
    };
  }, []);

  const health = useSystemHealth(REFRESH_MS, autoRefresh);
  const { lamp, label } = statusPresentation(health);

  useEffect(() => {
    setNow(new Date());
  }, [health.lastCheckedAt]);

  const loadPanels = useRef(async (): Promise<void> => {
    const [jobsResult, providersResult] = await Promise.all([fetchJobsStatus(), fetchProviders()]);
    if (jobsResult.ok) {
      setJobs(jobsResult.data);
      setJobsError(null);
    } else {
      setJobsError(jobsResult.kind);
    }
    if (providersResult.ok) {
      setProviders(providersResult.data);
      setProvidersError(null);
    } else {
      setProvidersError(providersResult.kind);
    }
  });

  useEffect(() => {
    void loadPanels.current();
  }, [health.lastCheckedAt]);

  const firstLoad = health.phase === "loading" && health.firstLoad;

  return (
    <>
      <Panel title="Overall" titleId="overall-title">
        <div className="sunil-list__row">
          <Lamp state={lamp} label={`Overall status: ${label.toLowerCase()}`} />
          <span className="sunil-type-display-sm sunil-fg-accent" aria-hidden="true">
            {label}
          </span>
          <span className="sunil-list__row-label" />
          <span
            className="sunil-type-caption sunil-fg-secondary"
            title={
              health.lastCheckedAt === null
                ? undefined
                : isoWithOffset(health.lastCheckedAt, timeZone)
            }
          >
            {health.lastCheckedAt === null || now === null
              ? "Not checked yet"
              : `Last checked ${formatRelativeTime(health.lastCheckedAt, now)}`}
          </span>
          <Button variant="ghost" onClick={health.refresh}>
            Refresh
          </Button>
          <Button
            variant="text"
            aria-pressed={autoRefresh}
            onClick={() => {
              setAutoRefresh((value) => !value);
            }}
          >
            {autoRefresh ? "Auto-refresh on" : "Auto-refresh off"}
          </Button>
        </div>
        {reducedMotion ? (
          <p className="sunil-type-caption sunil-fg-secondary">
            Reduced motion is on, so auto-refresh starts switched off.
          </p>
        ) : null}
        {health.phase === "error" ? (
          <Alert>
            Could not reach the health endpoint.
            {health.httpStatus === null
              ? " No response from the server."
              : ` The server responded with a ${String(health.httpStatus).charAt(0)}xx status.`}
          </Alert>
        ) : null}
      </Panel>

      <section aria-labelledby="dependencies-title">
        <h2 className="sunil-type-eyebrow sunil-fg-heading" id="dependencies-title">
          Dependencies
        </h2>
        <div className="sunil-card-grid" aria-busy={firstLoad ? true : undefined}>
          {firstLoad ? <span className="sunil-sr-only">Loading system health</span> : null}
          {DEPENDENCIES.map((dependency) => {
            const value =
              dependency.depKey === null ? undefined : health.data?.deps[dependency.depKey];
            const failed = health.phase === "error";
            const state = failed
              ? { lamp: "off" as const, text: "NO SIGNAL" }
              : value === "up"
                ? { lamp: "on" as const, text: "ONLINE" }
                : value === "down"
                  ? { lamp: "error" as const, text: "DOWN" }
                  : { lamp: "unknown" as const, text: "NOT REPORTED" };
            return (
              <div className="sunil-card" key={dependency.label}>
                {firstLoad ? (
                  <Skeleton height={72} />
                ) : (
                  <>
                    <span className="sunil-card__title sunil-type-eyebrow">
                      {dependency.label}
                    </span>
                    <span className="sunil-list__row">
                      <Lamp state={state.lamp} label={`${dependency.label}: ${state.text}`} />
                      <span className="sunil-type-micro" aria-hidden="true">
                        {state.text}
                      </span>
                    </span>
                    <span className="sunil-type-caption">{dependency.detail}</span>
                  </>
                )}
              </div>
            );
          })}
        </div>
        <p className="sunil-type-caption sunil-fg-secondary">
          Latency is not reported by the Phase 1 health endpoint, so none is shown. No version,
          host or connection detail is exposed here by design (FR-091).
        </p>
      </section>

      <Panel title="Queues" titleId="queues-title">
        {jobsError !== null ? (
          <Alert>
            {jobsError === "forbidden"
              ? "Queue status needs the job:read permission, which this session does not have."
              : "Queue status unavailable."}
          </Alert>
        ) : jobs === null ? (
          <Skeleton height={64} />
        ) : (
          <>
            <div className="sunil-card-grid">
              <StatTile label="Waiting" value={jobs.counts.waiting} />
              <StatTile label="Active" value={jobs.counts.active} />
              <StatTile label="Completed" value={jobs.counts.completed} />
              <StatTile
                label="Failed"
                value={jobs.counts.failed}
                tone={jobs.counts.failed > 0 ? "danger" : "default"}
              />
              <StatTile label="Delayed" value={jobs.counts.delayed} />
            </div>
            {jobs.counts.completed === 0 && jobs.counts.active === 0 ? (
              <p className="sunil-type-caption sunil-fg-secondary">No jobs have run yet.</p>
            ) : null}
            {jobs.repeatableKeys.length === 0 ? (
              <p className="sunil-type-caption sunil-fg-secondary">
                No repeatable jobs registered.
              </p>
            ) : (
              <ul className="sunil-list sunil-type-caption">
                {jobs.repeatableKeys.map((key) => (
                  <li className="sunil-list__row" key={key}>
                    {key}
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </Panel>

      <Panel title="LLM providers" titleId="providers-title">
        {providersError !== null ? (
          <Alert>
            {providersError === "forbidden"
              ? "Provider status needs the provider:read permission, which this session does not have."
              : "Could not load providers."}
          </Alert>
        ) : providers === null ? (
          <Skeleton height={64} />
        ) : providers.length === 0 ? (
          <EmptyState>No providers configured.</EmptyState>
        ) : (
          <div className="sunil-list">
            {providers.map((provider) => (
              <div className="sunil-sysrow" key={provider.id}>
                {/* Never a green lamp here, under any circumstance (FR-065). */}
                <Lamp state="unknown" label={`${provider.slug}: ${providerLabel(provider)}`} />
                <span className="sunil-sysrow__name sunil-type-caption" aria-hidden="true">
                  {provider.slug}
                </span>
                <span className="sunil-sysrow__state sunil-type-micro" aria-hidden="true">
                  {providerLabel(provider)}
                </span>
              </div>
            ))}
          </div>
        )}
        <p className="sunil-type-caption sunil-fg-secondary">
          Provider adapters have not been verified against live endpoints in Phase 1.
        </p>
      </Panel>
    </>
  );
}
