"use client";

/**
 * The header system-status pill — PORTAL_SHELL_SPEC.md §4.1.
 *
 * Never colour-only: the text label always renders (SC 1.4.1). It is a LINK to
 * `/system-health`, because a status indicator that cannot be acted on is an ornament.
 *
 * It announces only a CHANGE of state, into the app-wide polite region owned by the shell.
 */
import { useEffect, useRef } from "react";
import type { JSX } from "react";
import { Lamp } from "@sunil/ui";
import { statusPresentation, useSystemHealth } from "../lib/api/useSystemHealth";

const POLL_MS = 30_000;

export function SystemStatusPill({
  onAnnounce,
}: {
  onAnnounce?: (message: string) => void;
}): JSX.Element {
  const health = useSystemHealth(POLL_MS);
  const { lamp, label } = statusPresentation(health);
  const previous = useRef<string | null>(null);

  useEffect(() => {
    if (health.phase === "loading") return;
    if (previous.current !== null && previous.current !== label) {
      onAnnounce?.(`System status: ${label.toLowerCase()}`);
    }
    previous.current = label;
  }, [label, health.phase, onAnnounce]);

  return (
    <a className="sunil-status-pill" href="/system-health">
      <Lamp state={lamp} label={`System status: ${label.toLowerCase()}`} />
      <span className="sunil-type-micro" aria-hidden="true">
        {label}
      </span>
    </a>
  );
}
