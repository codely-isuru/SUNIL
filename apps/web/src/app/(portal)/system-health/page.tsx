/**
 * `/system-health` — PORTAL_SHELL_SPEC.md §10, FR-091, FR-085, FR-065.
 *
 * The data is fetched on the CLIENT, not in this server component, for two reasons: the page
 * polls anyway (§10.2), and a server-side fetch would make `next build` depend on the API
 * being up. The four states then get exercised for real rather than assumed.
 */
import type { JSX } from "react";
import type { Metadata } from "next";
import { SystemHealthView } from "../../../components/SystemHealthView";

export const metadata: Metadata = { title: "System Health" };

export default function SystemHealthPage(): JSX.Element {
  return <SystemHealthView />;
}
